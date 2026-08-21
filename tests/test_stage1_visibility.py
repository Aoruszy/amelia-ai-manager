from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from amelia_manager.admin import create_app
from amelia_manager.company_profile import load_company_profile
from amelia_manager.conversation_engine import ConversationEngine, _format_order_card_context
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.events import EventName
from amelia_manager.order_card import OrderCard, merge_order_patch, merge_order_state, unapplied_order_patch_field_codes
from amelia_manager.order_state import extract_order_state
from amelia_manager.outbound import send_workload_warnings
from amelia_manager.telegram_runtime import update_active_order_from_messages_with_llm


class JsonLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def generate(self, prompt: str, **kwargs) -> str:
        return self.payload


class CapturingTelegram:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str):
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append((chat_id, text))


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite:///{tmp_path / 'stage1.sqlite3'}",
        "admin_username": "admin",
        "admin_password": "secret",
        "admin_chat_id": 999,
    }
    values.update(overrides)
    return Settings(**values)


def _repo(tmp_path) -> SQLiteRepository:
    repo = SQLiteRepository(tmp_path / "stage1.sqlite3")
    repo.initialize()
    return repo


def _base_order(**overrides) -> OrderCard:
    values = dict(
        budget=5000,
        colors=["розы"],
        fulfillment_type="delivery",
        delivery_date="2026-08-20",
        delivery_time="14:00",
        address="Гайдара 173",
        sender_name="Даниил",
        sender_phone="89990000001",
        recipient_name="Анна",
        recipient_phone="89990000002",
        payment_method="transfer",
    )
    values.update(overrides)
    return OrderCard(**values)


@pytest.mark.asyncio
async def test_deferred_date_and_time_are_dialogue_branches_until_confirmed():
    engine = ConversationEngine(llm=JsonLLM('{"reply":"ignored"}'), company_profile=load_company_profile("amelia_flowers"))
    date_card = _base_order(delivery_date=None, delivery_time=None)
    time_card = _base_order(delivery_time=None)

    date_action = await engine.handle_messages(client_summary="", recent_messages=["Клиент: не важно"], stage="order", order_card=date_card)
    time_action = await engine.handle_messages(client_summary="", recent_messages=["Клиент: когда удобно"], stage="order", order_card=time_card)

    assert date_action.messages == ["Могу записать на завтра — подойдёт?"]
    assert time_action.messages == ["Давайте к 14:00, удобно?"]
    assert date_action.order_patch == {}
    assert time_action.order_patch == {}


def test_confirmed_deferred_date_and_time_allow_order_to_be_ready():
    card = _base_order(delivery_date=None, delivery_time=None)
    date_state = extract_order_state(
        ["Менеджер: Могу записать на завтра — подойдёт?", "Клиент: да"],
        today=date(2026, 8, 19),
    )
    card = merge_order_state(card, date_state)
    time_state = extract_order_state(["Менеджер: Давайте к 14:00, удобно?", "Клиент: да"], today=date(2026, 8, 19))
    card = merge_order_state(card, time_state)

    assert card.delivery_date == "2026-08-20"
    assert card.delivery_time == "14:00"
    assert card.is_ready_for_admin_request()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_date", ["tomorrow", "завтра", "23 августа", ""])
async def test_llm_invalid_delivery_dates_are_rejected_and_observable(tmp_path, bad_date):
    repo = _repo(tmp_path)
    client = repo.upsert_client(telegram_id=1, username="client")

    card = await update_active_order_from_messages_with_llm(
        repo,
        llm=JsonLLM(f'{{"delivery_date": "{bad_date}"}}'),
        client_id=client.id,
        recent_messages=["Клиент: завтра"],
        company_profile=load_company_profile("amelia_flowers"),
        today=date(2026, 8, 19),
    )

    assert card.delivery_date != bad_date
    events = repo.list_events(client_id=client.id, event=EventName.CASE_PATCH_IGNORED)
    assert events
    assert "delivery_date" in events[-1].payload_json
    assert "_ignored_field_codes" not in card.custom_fields
    assert "_ignored_field_codes" not in _format_order_card_context(card)


@pytest.mark.asyncio
async def test_llm_valid_iso_date_and_hhmm_time_are_accepted_without_ignored_event(tmp_path):
    repo = _repo(tmp_path)
    client = repo.upsert_client(telegram_id=1, username="client")

    card = await update_active_order_from_messages_with_llm(
        repo,
        llm=JsonLLM('{"delivery_date": "2026-08-20", "delivery_time": "14:00"}'),
        client_id=client.id,
        recent_messages=["Клиент: на 20 августа в 14:00"],
        company_profile=load_company_profile("amelia_flowers"),
        today=date(2026, 8, 19),
    )

    assert card.delivery_date == "2026-08-20"
    assert card.delivery_time == "14:00"
    assert repo.list_events(client_id=client.id, event=EventName.CASE_PATCH_IGNORED) == []


def test_invalid_time_patch_is_rejected_but_none_is_not_error():
    card = merge_order_patch(OrderCard(), {"delivery_time": "вечером", "delivery_date": None})

    assert card.delivery_time is None
    assert unapplied_order_patch_field_codes({"delivery_time": "вечером", "delivery_date": None}) == ["delivery_time"]
    assert unapplied_order_patch_field_codes({"delivery_time": None, "delivery_date": None}) == []


def _add_order(repo: SQLiteRepository, *, telegram_id: int, status: str, card: OrderCard):
    client = repo.upsert_client(telegram_id=telegram_id, username=f"u{telegram_id}")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(order_id=order.id, card=card)
    if status != "draft":
        repo.update_order_status(order_id=order.id, status=status, changed_by="test")
    return client, repo.get_order_by_id(order.id)


def test_workload_page_requires_auth_and_shows_active_orders_by_db_range(tmp_path):
    repo = _repo(tmp_path)
    _add_order(repo, telegram_id=1, status="draft", card=OrderCard(fulfillment_type="pickup", delivery_date="2026-08-20", delivery_time="12:00", sender_name="Иван", budget=5000))
    _add_order(repo, telegram_id=2, status="submitted", card=OrderCard(fulfillment_type="delivery", delivery_date="2026-08-20", delivery_time=None, sender_name="Анна", budget=7000))
    _add_order(repo, telegram_id=5, status="draft", card=OrderCard(fulfillment_type="delivery", delivery_date="2026-08-20", delivery_time="23:00", sender_name="Поздно", budget=8000))
    _add_order(repo, telegram_id=3, status="fulfilled", card=OrderCard(fulfillment_type="delivery", delivery_date="2026-08-20", delivery_time="14:00", sender_name="Терминал", budget=9000))
    _add_order(repo, telegram_id=4, status="draft", card=OrderCard(fulfillment_type="delivery", delivery_date=None, sender_name="Без даты", budget=3000))
    settings = _settings(tmp_path, workload_horizon_days=3)
    client = TestClient(create_app(settings=settings))

    assert client.get("/workload").status_code == 401
    response = client.get("/workload?date_from=2026-08-19", auth=("admin", "secret"))

    assert response.status_code == 200
    assert "Загрузка" in response.text
    assert "2026-08-20" in response.text
    assert "Всего: 3" in response.text
    assert "Самовывоз: 1" in response.text
    assert "Доставка: 2" in response.text
    assert "Без времени" in response.text
    assert "Вне часов работы" in response.text
    assert "Анна" in response.text
    assert "Поздно" in response.text
    assert "Терминал" not in response.text
    assert "Без даты" in response.text
    assert "2026-08-22" not in response.text


def test_workload_outside_hours_depend_on_fulfillment_type(tmp_path):
    repo = _repo(tmp_path)
    _add_order(repo, telegram_id=11, status="draft", card=OrderCard(fulfillment_type="pickup", delivery_date="2026-08-20", delivery_time="20:30", sender_name="Поздний самовывоз"))
    _add_order(repo, telegram_id=12, status="draft", card=OrderCard(fulfillment_type="delivery", delivery_date="2026-08-20", delivery_time="20:30", sender_name="Доставка вечером"))
    _add_order(repo, telegram_id=13, status="draft", card=OrderCard(fulfillment_type="pickup", delivery_date="2026-08-20", delivery_time="19:00", sender_name="Самовывоз вовремя"))
    _add_order(repo, telegram_id=14, status="draft", card=OrderCard(fulfillment_type=None, delivery_date="2026-08-20", delivery_time="23:30", sender_name="Без формата поздно"))
    client = TestClient(create_app(settings=_settings(tmp_path, workload_horizon_days=2)))

    response = client.get("/workload?date_from=2026-08-20", auth=("admin", "secret"))

    assert response.status_code == 200
    outside_section = response.text.split("Вне часов работы", 1)[1]
    assert "Поздний самовывоз" in outside_section
    assert "Без формата поздно" in outside_section
    assert "Доставка вечером" not in outside_section
    assert "Самовывоз вовремя" not in outside_section


def test_workload_repository_keeps_filtering_in_sql_and_honors_horizon(tmp_path):
    repo = _repo(tmp_path)
    _add_order(repo, telegram_id=1, status="draft", card=OrderCard(delivery_date="2026-08-20", fulfillment_type="pickup"))
    _add_order(repo, telegram_id=2, status="draft", card=OrderCard(delivery_date="2026-09-20", fulfillment_type="delivery"))

    rows = repo.list_workload_orders(date_from=date(2026, 8, 19), date_to=date(2026, 8, 21))

    assert [row.order.id for row in rows] == [1]


@pytest.mark.asyncio
async def test_workload_warning_sends_once_and_only_when_threshold_enabled(tmp_path):
    repo = _repo(tmp_path)
    for idx in range(3):
        _add_order(repo, telegram_id=10 + idx, status="draft", card=OrderCard(delivery_date="2026-08-20", delivery_time="12:00", fulfillment_type="delivery" if idx == 0 else "pickup"))
    telegram = CapturingTelegram()
    settings = _settings(tmp_path, workload_warning_threshold=2)
    now = datetime(2026, 8, 19, 10, 0, tzinfo=ZoneInfo("Europe/Kaliningrad"))

    await send_workload_warnings(telegram, repo=repo, settings=settings, now=now)
    await send_workload_warnings(telegram, repo=repo, settings=settings, now=now)

    assert len(telegram.sent) == 1
    assert "2026-08-20" in telegram.sent[0][1]
    assert "заказов: 3" in telegram.sent[0][1]
    assert "доставка: 1" in telegram.sent[0][1]

    disabled = CapturingTelegram()
    await send_workload_warnings(disabled, repo=repo, settings=_settings(tmp_path, workload_warning_threshold=0), now=now)
    assert disabled.sent == []


def test_workload_warning_text_uses_profile_template_and_reads_for_1_2_5():
    profile = load_company_profile("amelia_flowers")
    template = profile.workload_warning_template

    rendered = [template.format(date="2026-08-20", total=total, delivery=0, pickup=total) for total in (1, 2, 5)]

    assert all("заказов:" in text for text in rendered)
    assert all("заказа" not in text for text in rendered)
    assert "Перегруз" in rendered[0]


@pytest.mark.asyncio
async def test_workload_warning_repeats_only_after_notable_growth_and_survives_send_error(tmp_path):
    repo = _repo(tmp_path)
    for idx in range(3):
        _add_order(repo, telegram_id=20 + idx, status="draft", card=OrderCard(delivery_date="2026-08-20", fulfillment_type="pickup"))
    settings = _settings(tmp_path, workload_warning_threshold=2, workload_warning_repeat_growth=2)
    now = datetime(2026, 8, 19, 10, 0, tzinfo=ZoneInfo("Europe/Kaliningrad"))

    await send_workload_warnings(CapturingTelegram(fail=True), repo=repo, settings=settings, now=now)
    assert repo.list_events(event=EventName.WORKLOAD_WARNING_SENT) == []

    ok = CapturingTelegram()
    await send_workload_warnings(ok, repo=repo, settings=settings, now=now)
    _add_order(repo, telegram_id=99, status="draft", card=OrderCard(delivery_date="2026-08-20", fulfillment_type="delivery"))
    await send_workload_warnings(ok, repo=repo, settings=settings, now=now)
    _add_order(repo, telegram_id=100, status="draft", card=OrderCard(delivery_date="2026-08-20", fulfillment_type="delivery"))
    await send_workload_warnings(ok, repo=repo, settings=settings, now=now)

    assert len(ok.sent) == 2
