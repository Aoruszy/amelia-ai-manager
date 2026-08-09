from amelia_manager.company_profile import CompanyProfile
from amelia_manager.config import Settings
from amelia_manager.telegram_runtime import should_use_llm_extractor


def test_llm_extractor_can_be_disabled_for_amelia_when_config_disabled():
    settings = Settings(llm_extractor_enabled=False)
    profile = CompanyProfile(
        company_name="Amelia Flowers",
        manager_name="Алина",
        business_type="florist",
        city="Калининград",
        tone="живой",
    )

    assert should_use_llm_extractor(settings, company_profile=profile) is False


def test_llm_extractor_explicit_disabled_applies_to_non_florist_profiles():
    settings = Settings(llm_extractor_enabled=False)
    profile = CompanyProfile(
        company_name="Dental Plus",
        manager_name="Марина",
        business_type="clinic",
        city="Калининград",
        tone="спокойный",
    )

    assert should_use_llm_extractor(settings, company_profile=profile) is False
