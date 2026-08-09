from pathlib import Path

from amelia_manager.telegram_login import get_session_path, validate_login_settings
from amelia_manager.config import Settings


def test_get_session_path_uses_data_directory():
    settings = Settings(telegram_session_name="amelia_manager")

    assert get_session_path(settings) == Path("data/sessions/amelia_manager")


def test_validate_login_settings_reports_missing_values():
    settings = Settings(
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_phone=None,
    )

    missing = validate_login_settings(settings)

    assert missing == ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE"]


def test_validate_login_settings_passes_when_required_values_exist():
    settings = Settings(
        telegram_api_id=123,
        telegram_api_hash="hash",
        telegram_phone="+79990000009",
    )

    assert validate_login_settings(settings) == []
