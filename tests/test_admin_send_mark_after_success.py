import pytest

from amelia_manager.company_profile import load_company_profile
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import send_admin_order_request_if_ready


READY_PICKUP = OrderCard(
    budget=7500,
    colors=["розы"],
    fulfillment_type="pickup",
    delivery_date="2026-08-10",
    delivery_time="18:00",
    sender_name="Даниил",
    sender_phone="89990000001",
)


class FailingClient:
    async def send_message(self, chat_id, text):
        raise RuntimeError("telegram send failed")


class CapturingClient:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


@pytest.mark.asyncio
async def test_admin_request_is_not_marked_sent_when_telegram_send_fails(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="dummy")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(order_id=order.id, card=READY_PICKUP)
    order = repo.get_active_order(client_id=client.id)

    with pytest.raises(RuntimeError):
        await send_admin_order_request_if_ready(
            FailingClient(),
            repo=repo,
            order=order,
            admin_chat_id=999,
            client_label="@dummy / 123",
            company_profile=load_company_profile("amelia_flowers"),
        )

    assert repo.get_active_order(client_id=client.id).card.admin_request_sent is False


@pytest.mark.asyncio
async def test_admin_request_marked_sent_only_after_successful_send(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    db_client = repo.upsert_client(telegram_id=123, username="dummy")
    order = repo.get_or_create_active_order(client_id=db_client.id)
    repo.update_order_card(order_id=order.id, card=READY_PICKUP)
    order = repo.get_active_order(client_id=db_client.id)
    telegram = CapturingClient()

    sent = await send_admin_order_request_if_ready(
        telegram,
        repo=repo,
        order=order,
        admin_chat_id=999,
        client_label="@dummy / 123",
        company_profile=load_company_profile("amelia_flowers"),
    )

    assert sent is True
    assert telegram.messages
    updated = repo.get_active_order(client_id=db_client.id).card
    assert updated.admin_request_sent is True
    assert updated.client_summary_sent is True
