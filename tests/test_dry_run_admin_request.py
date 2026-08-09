from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import build_admin_order_request_if_needed


def test_admin_request_preview_does_not_mark_order_sent(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    order = repo.get_or_create_active_order(client_id=client.id)
    ready = OrderCard(
        budget=5000,
        colors=["нежный стиль"],
        fulfillment_type="pickup",
        delivery_date="today",
        delivery_time="18:00",
        sender_name="Ольга",
        sender_phone="89990000001",
    )
    repo.update_order_card(order_id=order.id, card=ready)
    order = repo.get_active_order(client_id=client.id)

    text = build_admin_order_request_if_needed(repo, order=order, client_label="client", mark_sent=False)
    after = repo.get_active_order(client_id=client.id)

    assert text is not None
    assert after.card.admin_request_sent is False
    assert after.card.client_summary_sent is False
