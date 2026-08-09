from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import update_active_order_from_messages


def test_restart_marker_in_history_does_not_reset_again_on_later_budget(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    current_order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=current_order.id,
        card=OrderCard(fulfillment_type="delivery", address="Гайдара 173", recipient_name="Ольга", recipient_phone="89990000005"),
    )

    card = update_active_order_from_messages(
        repo,
        client_id=client.id,
        recent_messages=[
            "Клиент: Здравствуйте нужна доставка на Гайдара 173",
            "Менеджер: Подскажите, пожалуйста, имя и номер телефона получателя?",
            "Клиент: Ольга 89990000005",
            "Менеджер: Подскажите бюджет и пожелания к букету?",
            "Клиент: до 5000, нежный",
        ],
    )
    active = repo.get_active_order(client_id=client.id)

    assert active.id == current_order.id
    assert card.address == "Гайдара 173"
    assert card.budget == 5000
    assert "нежный стиль" in card.colors
