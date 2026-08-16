from amelia_manager.config import Settings


def test_settings_defaults_are_safe_for_initial_run(monkeypatch):
    for name in ("AUTO_REPLY_ENABLED", "LLM_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.manager_name == "Алина"
    assert settings.llm_provider == "openai"
    assert settings.llm_model == "gpt-5.6-luna"
    assert settings.auto_reply_enabled is False
    assert settings.allow_only_test_users is False
    assert settings.min_reply_delay_seconds >= 1
    assert settings.max_reply_delay_seconds >= settings.min_reply_delay_seconds


def test_allowlist_parses_comma_separated_ids():
    settings = Settings(test_allowlist_ids="123, 456,789")

    assert settings.allowlist_ids == {123, 456, 789}
