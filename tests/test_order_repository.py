from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard


def test_repository_creates_and_updates_active_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")

    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(order_id=order.id, card=OrderCard(budget=5000, fulfillment_type="pickup"))

    loaded = repo.get_active_order(client_id=client.id)

    assert loaded is not None
    assert loaded.id == order.id
    assert loaded.card.budget == 5000
    assert loaded.card.fulfillment_type == "pickup"
