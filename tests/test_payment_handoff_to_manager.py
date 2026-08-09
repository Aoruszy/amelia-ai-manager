import pytest

from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.order_card import OrderCard
from amelia_manager.safety import check_reply_safety


class ShouldNotCallLLM:
    async def generate(self, prompt: str) -> str:
        raise AssertionError("ready order summary should be deterministic")


READY_DELIVERY_CARD_WITH_TRANSFER = OrderCard(
    budget=5000,
    colors=["белый"],
    fulfillment_type="delivery",
    delivery_date="15 августа",
    delivery_time="18:00",
    address="Гайдара 172",
    sender_name="Даниил",
    sender_phone="89990000012",
    recipient_name="Ольга",
    recipient_phone="89990000011",
    payment_method="transfer",
)


def test_client_summary_says_manager_handles_payment_not_order_confirmed():
    summary = format_client_order_summary(READY_DELIVERY_CARD_WITH_TRANSFER)

    assert "менеджер" in summary.lower()
    assert "реквизит" in summary.lower() or "ссыл" in summary.lower()
    assert "заказ подтвержден" not in summary.lower().replace("ё", "е")
    assert "оплату" not in summary.lower() or "зафиксировала" not in summary.lower()
    assert "курьер" not in summary.lower()


@pytest.mark.asyncio
async def test_engine_ready_delivery_payment_uses_manager_payment_handoff_summary():
    action = await ConversationEngine(ShouldNotCallLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: СБП"],
        stage="ordering",
        order_card=READY_DELIVERY_CARD_WITH_TRANSFER,
    )

    assert action.kind == "send"
    text = "\n".join(action.messages).lower().replace("ё", "е")
    assert "менеджер" in text
    assert "реквизит" in text or "ссыл" in text
    assert "заказ подтвержден" not in text
    assert "оплату по сбп зафиксировала" not in text
    assert "передам курьеру" not in text


def test_safety_rejects_ai_claiming_payment_or_order_confirmation():
    result = check_reply_safety(
        "Заказ подтвержден 🤍 Оплату по СБП зафиксировала, букет соберу и передам курьеру к 18:00."
    )

    assert not result.is_safe
    assert "payment_confirmation_without_manager" in result.reasons
