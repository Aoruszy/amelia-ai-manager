from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import build_admin_order_request_if_needed


def test_admin_request_marks_client_summary_sent_with_admin_request(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    card = OrderCard(
        budget=10000,
        colors=["белый", "кремовый", "нежный стиль"],
        fulfillment_type="pickup",
        delivery_date="12 августа",
        delivery_time="12:00",
        sender_name="Даниил",
        sender_phone="89990000005",
        payment_method="cash",
    )
    repo.update_order_card(order_id=order.id, card=card)
    order = repo.get_active_order(client_id=client.id)

    request = build_admin_order_request_if_needed(repo, order=order, client_label="@test")

    assert request is not None
    updated = repo.get_active_order(client_id=client.id)
    assert updated.card.admin_request_sent is True
    assert updated.card.client_summary_sent is True
