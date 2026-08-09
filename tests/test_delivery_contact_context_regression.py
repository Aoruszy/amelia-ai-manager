from amelia_manager.order_state import extract_order_state


def test_delivery_contacts_follow_manager_questions_when_recipient_comes_before_sender():
    state = extract_order_state(
        [
            "Клиент: Давайте доставку",
            "Менеджер: На какой адрес нужно привезти букет?",
            "Клиент: Гайдара 172",
            "Менеджер: На какое время и на какую дату планируете доставку?",
            "Клиент: 15 августа 18:00",
            "Менеджер: Подскажите, как зовут получателя и какой у него номер телефона?",
            "Клиент: Ольга 89990000011",
            "Менеджер: Записала имя получателя и номер. Подскажите ещё, как зовут вас и ваш номер телефона для связи?",
            "Клиент: Даниил 89990000012",
        ]
    )

    assert state.address == "Гайдара 172"
    assert state.delivery_date == "2026-08-15"
    assert state.delivery_time == "18:00"
    assert state.recipient_name == "Ольга"
    assert state.recipient_phone == "89990000011"
    assert state.sender_name == "Даниил"
    assert state.sender_phone == "89990000012"


def test_delivery_date_time_is_not_extracted_as_address_after_delivery_context():
    state = extract_order_state(
        [
            "Клиент: Доставка",
            "Клиент: Гайдара 172",
            "Клиент: 15 августа 18:00",
        ]
    )

    assert state.address == "Гайдара 172"
