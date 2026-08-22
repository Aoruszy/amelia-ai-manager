from amelia_manager.deterministic_replies import deterministic_order_reply
from amelia_manager.company_profile import load_company_profile
from amelia_manager.conversation_engine import _ensure_pickup_address_for_pickup_time
from amelia_manager.order_card import OrderCard
from amelia_manager.order_policy import NextStep


def test_deterministic_when_where_reply_uses_missing_fields_not_full_question():
    reply = deterministic_order_reply(
        NextStep(
            "ask_when_where",
            "Уточни только недостающие поля.",
            missing=("delivery_time", "address"),
        ),
        OrderCard(fulfillment_type="delivery", delivery_date="2026-08-22"),
    )

    assert reply is not None
    lowered = reply.lower()
    assert "время" in lowered or "к какому" in lowered
    assert "адрес" in lowered
    assert "когда" not in lowered
    assert "доставка или самовывоз" not in lowered


def test_deterministic_when_where_pickup_missing_time_includes_pickup_address_not_delivery_address():
    reply = deterministic_order_reply(
        NextStep("ask_when_where", "Уточни время.", missing=("delivery_time",), fulfillment_type="pickup"),
        OrderCard(fulfillment_type="pickup", delivery_date="2026-08-22"),
    )

    assert reply is not None
    assert "Сергеева, 61" in reply
    assert "адрес доставки" not in reply.lower()
    assert "время" in reply.lower() or "к какому" in reply.lower()


def test_deterministic_when_where_pickup_missing_time_uses_explicit_format_not_instruction_text():
    reply = deterministic_order_reply(
        NextStep("ask_when_where", "Уточни время получения.", missing=("delivery_time",), fulfillment_type="pickup"),
        OrderCard(fulfillment_type="pickup", delivery_date="2026-08-22"),
    )

    assert reply is not None
    assert "Сергеева, 61" in reply
    assert "самовывоз" in reply.lower() or "забрать" in reply.lower()


def test_pickup_address_guard_runs_for_grouped_pickup_time_question_without_model_address():
    reply = _ensure_pickup_address_for_pickup_time(
        "К какому времени вам удобно забрать букет?",
        "ask_when_where",
        OrderCard(fulfillment_type="pickup", delivery_date="2026-08-22"),
        load_company_profile("amelia_flowers"),
    )

    assert "Сергеева, 61" in reply


def test_deterministic_contacts_reply_asks_both_roles_for_delivery():
    reply = deterministic_order_reply(
        NextStep(
            "ask_contacts",
            "Попроси контакты отправителя и получателя.",
            missing=("sender_name", "sender_phone", "recipient_name", "recipient_phone"),
        ),
        OrderCard(fulfillment_type="delivery"),
    )

    assert reply is not None
    lowered = reply.lower()
    assert "ваше имя" in lowered or "отправител" in lowered
    assert "получател" in lowered
    assert "телефон" in lowered


def test_deterministic_contacts_reply_for_single_sender_phone_does_not_ask_recipient():
    reply = deterministic_order_reply(
        NextStep("ask_contacts", "Попроси телефон отправителя.", missing=("sender_phone",)),
        OrderCard(fulfillment_type="delivery", sender_name="Анна"),
    )

    assert reply is not None
    lowered = reply.lower()
    assert "телефон" in lowered
    assert "получател" not in lowered
