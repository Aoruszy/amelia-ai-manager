from amelia_manager.config import Settings
from amelia_manager.company_profile import load_company_profile


def test_settings_has_default_company_profile_name():
    settings = Settings(
        telegram_api_id=123,
        telegram_api_hash="hash",
        telegram_phone="+79990000009",
        admin_chat_id=1,
        llm_api_key="key",
    )

    assert settings.company_profile_name == "amelia_flowers"
    assert load_company_profile(settings.company_profile_name).company_name == "Amelia Flowers"
