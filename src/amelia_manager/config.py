from __future__ import annotations

from functools import cached_property

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Product/persona
    manager_name: str = "Алина"
    company_profile_name: str = "amelia_flowers"

    # Telegram user account
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_phone: str | None = None
    telegram_session_name: str = "amelia_manager"

    # Admin
    admin_chat_id: int | None = None
    test_allowlist_ids: str = ""
    admin_username: str = "admin"
    admin_password: str = "admin"

    # LLM
    llm_provider: str = "gemini"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "gemini-flash-lite-latest"
    llm_extractor_enabled: bool = True

    # App
    app_env: str = "development"
    database_url: str = "sqlite:///data/amelia_manager.sqlite3"
    log_level: str = "INFO"
    auto_reply_enabled: bool = False
    allow_only_test_users: bool = False

    # Behavior
    min_reply_delay_seconds: int = Field(default=12, ge=1)
    max_reply_delay_seconds: int = Field(default=90, ge=1)
    message_buffer_seconds: int = Field(default=20, ge=0)
    conversation_history_limit: int = Field(default=20, ge=1, le=30)
    conversation_memory_days: int = Field(default=7, ge=1, le=30)
    pii_retention_days: int = Field(default=30, ge=1, le=3650)
    max_reply_chars: int = Field(default=400, ge=100, le=1000)
    work_hours_start: str = "09:00"
    work_hours_end: str = "20:00"
    delivery_hours_start: str = "08:00"
    delivery_hours_end: str = "22:00"
    scheduler_interval_minutes: int = Field(default=15, ge=1, le=1440)

    @field_validator("max_reply_delay_seconds")
    @classmethod
    def max_delay_must_not_be_less_than_min(cls, value: int, info):
        min_delay = info.data.get("min_reply_delay_seconds", 1)
        if value < min_delay:
            raise ValueError("max_reply_delay_seconds must be >= min_reply_delay_seconds")
        return value

    @cached_property
    def allowlist_ids(self) -> set[int]:
        if not self.test_allowlist_ids.strip():
            return set()
        ids: set[int] = set()
        for raw_id in self.test_allowlist_ids.split(","):
            raw_id = raw_id.strip()
            if raw_id:
                ids.add(int(raw_id))
        return ids
