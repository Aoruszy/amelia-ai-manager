from amelia_manager.safety import check_reply_safety


def test_safety_rejects_delivery_to_shop_address_hallucination():
    result = check_reply_safety("Записала доставку на сегодня к 20:00 на Сергеева 61")

    assert not result.is_safe
    assert "shop_address_as_delivery" in result.reasons


def test_safety_rejects_pickup_recipient_question():
    result = check_reply_safety("Для самовывоза подскажите номер телефона получателя")

    assert not result.is_safe
    assert "pickup_recipient_question" in result.reasons
