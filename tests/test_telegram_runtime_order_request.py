from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import build_admin_order_request_if_needed


def test_build_admin_order_request_if_needed_marks_order_sent(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard(
            budget=5000,
            colors=["синий", "белый"],
            fulfillment_type="pickup",
            delivery_date="today",
            delivery_time="18:00",
            sender_name="Даниил",
            sender_phone="89990000006",
            payment_method="transfer",
        ),
    )
    order = repo.get_active_order(client_id=client.id)

    text = build_admin_order_request_if_needed(repo, order=order, client_label="@client / 123")
    second_text = build_admin_order_request_if_needed(repo, order=repo.get_active_order(client_id=client.id), client_label="@client / 123")

    assert text is not None
    assert "Новая заявка Amelia Flowers" in text
    assert second_text is None
    assert repo.get_active_order(client_id=client.id).card.admin_request_sent is True
