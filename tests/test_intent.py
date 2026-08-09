from amelia_manager.intent import is_greeting_only


def test_detects_plain_greeting_only():
    assert is_greeting_only("Здравствуйте") is True
    assert is_greeting_only("Добрый день") is True
    assert is_greeting_only("привет") is True
    assert is_greeting_only("Здравствуйте!") is True


def test_does_not_treat_request_as_greeting_only():
    assert is_greeting_only("Здравствуйте, нужен букет") is False
    assert is_greeting_only("Добрый день, сколько стоит доставка?") is False
    assert is_greeting_only("Привет, хочу розы") is False
