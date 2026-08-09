from amelia_manager.safety import check_reply_safety


def test_reply_must_not_promise_photo_when_not_requested():
    result = check_reply_safety("Скоро пришлю фото сборки 🌸")

    assert result.is_safe is False
    assert "unsupported_photo_promise" in result.reasons


def test_reply_must_not_claim_florist_confirmation_without_actual_handoff():
    result = check_reply_safety("Уточню у флориста детали по наличию и скоро вернусь")

    assert result.is_safe is False
    assert "unsupported_handoff_promise" in result.reasons
