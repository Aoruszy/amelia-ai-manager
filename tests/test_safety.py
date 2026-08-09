from amelia_manager.safety import SafetyResult, check_reply_safety


def test_safe_reply_passes():
    result = check_reply_safety("Да, конечно. Букет нужен на сегодня или на другую дату?")

    assert result == SafetyResult(is_safe=True, reasons=[])


def test_reply_must_not_say_it_is_ai_or_bot():
    result = check_reply_safety("Я AI-бот и помогу оформить заказ")

    assert result.is_safe is False
    assert "identity_disclosure" in result.reasons


def test_reply_must_not_promise_exact_stock():
    result = check_reply_safety("Да, точно есть эти розы, гарантирую")

    assert result.is_safe is False
    assert "unverified_stock_promise" in result.reasons


def test_reply_must_not_guarantee_minute_exact_delivery():
    result = check_reply_safety("Гарантирую доставку ровно к 18:00, без задержек")

    assert result.is_safe is False
    assert "exact_delivery_guarantee" in result.reasons
