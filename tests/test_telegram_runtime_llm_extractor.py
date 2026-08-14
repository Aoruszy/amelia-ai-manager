import pytest

from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.telegram_runtime import update_active_order_from_messages_with_llm


class FakeLLM:
    async def generate(self, prompt: str) -> str:
        return '{"payment_method": "transfer", "delivery_time": "18:00"}'


@pytest.mark.asyncio
async def test_update_active_order_from_messages_with_llm_merges_llm_fields(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username=None)

    card = await update_active_order_from_messages_with_llm(
        repo,
        llm=FakeLLM(),
        client_id=client.id,
        recent_messages=["Менеджер: С каким бюджетом сориентировать вас по букету?", "Клиент: 5000", "Клиент: Самовывоз", "Клиент: оплачу переводом к шести"],
    )

    assert card.budget == 5000
    assert card.fulfillment_type == "pickup"
    assert card.delivery_time == "18:00"
    assert card.payment_method == "transfer"
