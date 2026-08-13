from amelia_manager.safety import check_reply_safety


def test_raw_json_like_model_output_is_unsafe():
    result = check_reply_safety('{"intent":"order","reply":"Привет","case_patch":{},"confidence":0.9}')

    assert not result.is_safe
    assert "raw_model_output" in result.reasons


def test_raw_array_like_model_output_is_unsafe():
    result = check_reply_safety('[{"reply":"Привет"}]')

    assert not result.is_safe
    assert "raw_model_output" in result.reasons


def test_bouquet_price_with_za_without_approximation_is_blocked():
    result = check_reply_safety("Нежный пастельный букет за 4200 ₽ можно собрать.")

    assert not result.is_safe
    assert "unsupported_price_quote" in result.reasons


def test_bouquet_price_with_za_and_approximation_is_allowed():
    result = check_reply_safety("Нежный пастельный букет примерно за 4200 ₽ можно собрать.")

    assert result.is_safe


def test_non_price_za_context_is_not_treated_as_price_quote():
    assert check_reply_safety("Заберу за час и спасибо за 5 минут.").is_safe
