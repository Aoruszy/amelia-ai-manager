from amelia_manager.safety import check_reply_safety


def test_safety_allows_available_stock_reply_that_matches_context():
    result = check_reply_safety(
        "Пионы в наличии, можем оформить.",
        stock_context="По наличию на сегодня релевантно:\n- пионы — 10",
    )

    assert result.is_safe is True


def test_safety_blocks_reply_claiming_unavailable_stock_from_context():
    result = check_reply_safety(
        "Да, пионы есть в наличии, можно оформить.",
        stock_context="По наличию на сегодня релевантно:\n- пионы — нет",
    )

    assert result.is_safe is False
    assert "stock_context_contradiction" in result.reasons


def test_safety_allows_unavailable_stock_reply_that_matches_context():
    result = check_reply_safety(
        "Пионов сегодня нет, могу предложить альтернативу.",
        stock_context="По наличию на сегодня релевантно:\n- пионы — нет",
    )

    assert result.is_safe is True
