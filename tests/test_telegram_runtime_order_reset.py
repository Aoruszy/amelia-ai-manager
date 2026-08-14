from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import should_start_new_order, update_active_order_from_messages


def test_should_not_start_new_order_for_generic_clarification_on_unfinished_order():
    old_card = OrderCard(
        budget=7000,
        colors=["синий"],
        fulfillment_type="delivery",
        delivery_date="tomorrow",
        delivery_time="13:00",
        address="Гайдара 173",
    )

    assert should_start_new_order("Нужны цветы", old_card) is False


def test_update_active_order_keeps_unfinished_order_for_fresh_request(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username=None)
    old_order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(order_id=old_order.id, card=OrderCard(budget=7000, fulfillment_type="delivery", delivery_date="tomorrow"))

    card = update_active_order_from_messages(
        repo,
        client_id=client.id,
        recent_messages=["Клиент: Нужны цветы"],
    )

    active = repo.get_active_order(client_id=client.id)
    assert active.id == old_order.id
    assert card.budget == 7000
    assert card.fulfillment_type == "delivery"
