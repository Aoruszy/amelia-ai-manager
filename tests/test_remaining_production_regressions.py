from datetime import date

import pytest

from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.order_state import extract_order_state
from amelia_manager.safety import check_reply_safety
from amelia_manager.telegram_runtime import send_pending_admin_requests


class LowConfidenceRiskyTextLLM:
    async def generate(self, prompt: str) -> str:
        return '{"intent":"uncertain","reply":"Наверное, можно, но я не уверена и могу ошибаться.","confidence":0.34,"needs_human":false}'


class CapturingClient:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


def test_month_day_without_year_rolls_to_next_year_if_already_past():
    today = date(2026, 8, 9)

    assert extract_order_state(["Клиент: букет на 8 марта"], today=today).delivery_date == "2027-03-08"
    assert extract_order_state(["Клиент: доставка 1 января"], today=today).delivery_date == "2027-01-01"


def test_explicit_past_year_is_preserved_for_admin_visibility():
    state = extract_order_state(["Клиент: букет на 8 марта 2026"], today=date(2026, 8, 9))

    assert state.delivery_date == "2026-03-08"


def test_delivery_address_on_prospect_is_extracted_without_llm():
    state = extract_order_state(["Клиент: доставка на Ленинский проспект 12"], today=date(2026, 8, 9))

    assert state.address == "Ленинский проспект 12"


def test_stock_intent_to_clarify_is_not_availability_promise_without_stock_context():
    result = check_reply_safety("Уточню, что сейчас в наличии, и напишу вам.")

    assert result.is_safe is True
    assert "unverified_stock_promise" not in result.reasons


@pytest.mark.asyncio
async def test_low_confidence_reply_uses_neutral_escalation_text_not_model_text():
    action = await ConversationEngine(LowConfidenceRiskyTextLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: не уверен, что надо"],
        stage="new_lead",
    )

    assert action.kind == "human_review"
    assert action.messages == ["Передам менеджеру, чтобы точно проверить и ответить вам корректно."]
    assert "Наверное" not in action.messages[0]


@pytest.mark.asyncio
async def test_pending_admin_requests_use_repository_public_active_order_listing(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="dummy")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard(
            budget=5000,
            colors=["розы"],
            fulfillment_type="pickup",
            delivery_date="2026-08-10",
            delivery_time="18:00",
            sender_name="Даниил",
            sender_phone="89990000001",
        ),
    )

    original_connect = repo._connect

    def fail_private_connect():
        raise AssertionError("runtime should not call repo._connect directly")

    pending = repo.list_active_orders_with_clients()
    monkeypatch.setattr(repo, "_connect", fail_private_connect)
    monkeypatch.setattr(repo, "list_active_orders_with_clients", lambda: pending)
    monkeypatch.setattr(repo, "get_active_order", lambda *, client_id: pending[0][0])

    # keep update path real enough for send_admin_order_request_if_ready
    monkeypatch.setattr(repo, "update_order_card", lambda **kwargs: None)
    sent = await send_pending_admin_requests(CapturingClient(), repo=repo, admin_chat_id=999)

    assert sent == 1
    assert original_connect is not None
