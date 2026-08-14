from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import update_active_order_from_messages


def test_continuation_after_new_order_start_does_not_merge_into_completed_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username=None)
    old_order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=old_order.id,
        card=OrderCard(
            budget=10000,
            colors=["белый", "кремовый"],
            fulfillment_type="pickup",
            delivery_date="12 августа",
            delivery_time="12:00",
            sender_name="Даниил",
            sender_phone="89990000005",
            payment_method="cash",
            admin_request_sent=True,
            client_summary_sent=True,
        ),
    )

    card = update_active_order_from_messages(
        repo,
        client_id=client.id,
        recent_messages=[
            "Менеджер: Итог заказа: старый заказ",
            "Клиент: Что за бред вы мне пишите !!",
            "Менеджер: Передам вопрос ответственному менеджеру.",
            "Клиент: Здравствуйте",
            "Менеджер: Здравствуйте 🙂 Чем могу помочь?",
            "Клиент: Хочу цветы купить",
            "Менеджер: С каким бюджетом сориентировать вас по букету?",
            "Клиент: 5000",
        ],
    )

    active = repo.get_active_order(client_id=client.id)
    assert active.id != old_order.id
    assert card.budget == 5000
    assert card.sender_name is None
    assert card.sender_phone is None
    assert card.payment_method is None
    assert card.admin_request_sent is False
    assert card.client_summary_sent is False
