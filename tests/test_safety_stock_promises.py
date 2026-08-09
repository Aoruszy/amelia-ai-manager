from amelia_manager.safety import check_reply_safety


def test_safety_blocks_unverified_stock_availability_phrases():
    result = check_reply_safety("Конечно, пионы в наличии, можно оформить.")

    assert result.is_safe is False
    assert "unverified_stock_promise" in result.reasons
