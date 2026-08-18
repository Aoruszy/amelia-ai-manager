from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from amelia_manager.company_profile import load_company_profile
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.events import EventName
from amelia_manager.metrics import calculate_metrics
from amelia_manager.model_decision import parse_model_decision
from amelia_manager.observability import EventRecorder
from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import (
    _looks_like_order_start,
    apply_new_order_start,
    is_order_abandoned,
    should_start_new_order,
    update_active_order_from_messages,
)


def _partial_card() -> OrderCard:
    return OrderCard(budget=5000, fulfillment_type="pickup")


def _sent_card() -> OrderCard:
    return OrderCard(
        budget=5000,
        colors=["розы"],
        fulfillment_type="pickup",
        delivery_date="завтра",
        delivery_time="12:00",
        sender_name="Даня",
        sender_phone="+79990000000",
        custom_fields={"occasion_sensitive": True},
        admin_request_sent=True,
    )


def test_partial_order_model_new_order_is_ignored_for_generic_clarifications():
    profile = load_company_profile("amelia_flowers")

    for text in ["нужен букет побольше", "хочу букет из роз", "нужны цветы пастельные"]:
        decision = should_start_new_order(text, _partial_card(), model_order_scope="new_order", company_profile=profile)
        assert decision.start is False
        assert decision.overridden is True


def test_partial_order_explicit_additional_marker_can_start_new_order():
    profile = load_company_profile("amelia_flowers")

    decision = should_start_new_order(
        "а можно ещё один букет маме, отдельно",
        _partial_card(),
        model_order_scope="new_order",
        company_profile=profile,
    )

    assert decision.start is True
    assert decision.scope == "new_order"
    assert decision.overridden is False


def test_sent_order_model_new_order_starts_and_transfers_only_sender_contacts(tmp_path):
    repo = SQLiteRepository(tmp_path / "orders.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    order = repo.get_or_create_active_order(client_id=client.id)
    old_card = _sent_card()
    repo.update_order_card(order_id=order.id, card=old_card)

    new_order = apply_new_order_start(repo, client_id=client.id, previous_order=order, updated_by="model")

    closed = repo.get_order_by_id(order.id)
    assert closed is not None
    assert closed.status == "completed"
    assert new_order.id != order.id
    assert new_order.card.sender_name == "Даня"
    assert new_order.card.sender_phone == "+79990000000"
    assert new_order.card.budget is None
    assert new_order.card.colors == []
    assert new_order.card.custom_fields == {}


def test_sent_order_model_continue_does_not_start_new_order_for_status_or_thanks():
    profile = load_company_profile("amelia_flowers")

    for text in ["а во сколько забирать?", "спасибо!"]:
        decision = should_start_new_order(text, _sent_card(), model_order_scope="continue", company_profile=profile)
        assert decision.start is False


def test_fallback_regex_cannot_reset_partial_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "orders.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(order_id=order.id, card=_partial_card())

    card = update_active_order_from_messages(repo, client_id=client.id, recent_messages=["Клиент: нужен букет"])

    active = repo.get_active_order(client_id=client.id)
    assert active is not None
    assert active.id == order.id
    assert card.budget == 5000
    assert card.fulfillment_type == "pickup"


def test_model_decision_order_scope_defaults_to_continue():
    assert parse_model_decision('{"reply":"ок","order_scope":"new_order"}').order_scope == "new_order"
    assert parse_model_decision('{"reply":"ок","order_scope":"nonsense"}').order_scope == "continue"
    assert parse_model_decision('{"reply":"ок"}').order_scope == "continue"


def test_order_scope_override_metric(tmp_path):
    repo = SQLiteRepository(tmp_path / "metrics.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    recorder = EventRecorder(repo)
    recorder.record(EventName.DIALOG_STARTED, client_id=client.id)
    recorder.record(EventName.ORDER_SCOPE_DECIDED, client_id=client.id, payload={"scope": "new_order", "overridden": True})
    recorder.record(EventName.ORDER_SCOPE_DECIDED, client_id=client.id, payload={"scope": "continue", "overridden": False})

    today = date.today()
    metrics = calculate_metrics(repo, date_from=today, date_to=today)

    assert metrics["quality"]["order_scope_override_rate"] == 0.5


def _stale_half_filled_card() -> OrderCard:
    """Заказ, брошенный на середине: поля есть, контактов нет, менеджеру не ушёл."""
    return OrderCard(budget=4000, fulfillment_type="pickup", delivery_date="2026-08-19", delivery_time="12:00")


def test_abandoned_half_filled_order_does_not_swallow_a_new_request():
    card = _stale_half_filled_card()

    for text in ("нужны цветочки", "нужны цветы", "хочу букет"):
        decision = should_start_new_order(text, card, model_order_scope="continue", previous_order_stale=True)
        assert decision.start is True, text


def test_fresh_half_filled_order_still_continues():
    """Негативный случай: пока заказ собирается, новое сообщение — продолжение, а не новый заказ."""
    card = _stale_half_filled_card()

    for text in ("нужны цветочки", "хочу букет", "5000", "самовывоз"):
        decision = should_start_new_order(text, card, model_order_scope="continue", previous_order_stale=False)
        assert decision.start is False, text


def test_abandoned_order_keeps_continuing_when_client_answers_a_question():
    """Негативный случай: просроченный заказ не сбрасывается от обычного ответа по делу."""
    card = _stale_half_filled_card()

    for text in ("5000", "самовывоз", "завтра к 12", "да, подтверждаю"):
        decision = should_start_new_order(text, card, model_order_scope="continue", previous_order_stale=True)
        assert decision.start is False, text


def test_order_start_detection_survives_diminutives_without_false_positives():
    assert _looks_like_order_start("нужны цветочки") is True
    assert _looks_like_order_start("закажу композицию") is True
    assert _looks_like_order_start("хочу корзину цветов") is True

    for text in ("5000", "самовывоз", "спасибо", "а сколько стоит доставка", "завтра к 12"):
        assert _looks_like_order_start(text) is False, text


def test_is_order_abandoned_uses_the_configured_threshold():
    settings = Settings(admin_username="x", admin_password="y", abandoned_order_days=3)
    now = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    def order(days_ago: float):
        return SimpleNamespace(updated_at=(now - timedelta(days=days_ago)).isoformat(), created_at=None)

    assert is_order_abandoned(order(5), settings=settings, now=now) is True
    assert is_order_abandoned(order(1), settings=settings, now=now) is False
    assert is_order_abandoned(SimpleNamespace(updated_at=None, created_at=None), settings=settings, now=now) is False
    assert is_order_abandoned(SimpleNamespace(updated_at="не дата", created_at=None), settings=settings, now=now) is False


def test_abandoned_order_is_reset_before_the_reply_is_composed(tmp_path):
    """Сброс должен случиться до движка, иначе первый ответ всё равно уйдёт со старой карточкой."""
    repo = SQLiteRepository(tmp_path / "scope.sqlite3")
    repo.initialize()
    settings = Settings(admin_username="x", admin_password="y", abandoned_order_days=3)
    client = repo.upsert_client(telegram_id=1, username="tester")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard(budget=4000, colors=["экзотический стиль"], fulfillment_type="pickup",
                       delivery_date="2026-08-19", delivery_time="12:00"),
    )
    with repo._connect() as conn:
        conn.execute(
            "UPDATE orders SET updated_at = ? WHERE id = ?",
            ((datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"), order.id),
        )
    messages = ["Клиент: Здравствуйте", "Менеджер: Здравствуйте 🙂 Чем могу помочь?", "Клиент: нужны цветочки"]

    card = update_active_order_from_messages(
        repo, client_id=client.id, recent_messages=messages, settings=settings, today=date(2026, 8, 16)
    )

    assert card.budget is None
    assert card.colors == []
    assert card.delivery_date is None
    assert card.fulfillment_type is None


def test_fresh_order_survives_the_same_dialog(tmp_path):
    repo = SQLiteRepository(tmp_path / "scope-fresh.sqlite3")
    repo.initialize()
    settings = Settings(admin_username="x", admin_password="y", abandoned_order_days=3)
    client = repo.upsert_client(telegram_id=2, username="fresh")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(order_id=order.id, card=OrderCard(budget=4000, colors=["экзотический стиль"]))
    messages = ["Клиент: Здравствуйте", "Менеджер: Здравствуйте 🙂 Чем могу помочь?", "Клиент: нужны цветочки"]

    card = update_active_order_from_messages(
        repo, client_id=client.id, recent_messages=messages, settings=settings, today=date(2026, 8, 16)
    )

    assert card.budget == 4000
    assert card.colors == ["экзотический стиль"]
