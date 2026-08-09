from amelia_manager.company_profile import CompanyProfile
from amelia_manager.config import Settings
from amelia_manager.telegram_runtime import should_use_llm_extractor


def test_llm_extractor_enabled_by_default_for_live_florist_profile():
    profile = CompanyProfile(
        company_name="Amelia Flowers",
        manager_name="Алина",
        business_type="florist",
        city="Калининград",
        tone="живой",
    )

    assert Settings().llm_extractor_enabled is True
    assert should_use_llm_extractor(Settings(), company_profile=profile) is True


def test_llm_extractor_can_be_explicitly_disabled_for_quota_control():
    assert should_use_llm_extractor(Settings(llm_extractor_enabled=False)) is False
