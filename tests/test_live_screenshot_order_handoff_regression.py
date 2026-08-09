from datetime import date

import pytest

from amelia_manager.config import Settings
from amelia_manager.company_profile import load_company_profile
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_extractor import extract_order_state_with_llm
from amelia_manager.order_state import extract_order_state
from amelia_manager.telegram_runtime import build_admin_order_request_if_needed, update_active_order_from_messages_with_optional_llm


SCREENSHOT_MESSAGES = [
    "Клиент: Нужны цветы",
    "Менеджер: Да, подберу букет 💐 На какую сумму ориентируетесь?",
    "Клиент: 7500",
    "Менеджер: Прекрасный бюджет ✨ Подскажите, пожалуйста, какие оттенки или стиль букета вам больше нравятся?",
    "Клиент: Давайте розы на всю сумму",
    "Менеджер: Поняла вас, сделаем из роз 🌹 Доставка или самовывоз?",
    "Клиент: Самовывоз",
    "Менеджер: Супер, самовывоз с Сергеева, 61 🌿 На какую дату и примерно к какому времени планируете забрать?",
    "Клиент: Завтра в 18:00",
    "Менеджер: Записала на завтра к 18:00 🌷 Подскажите, как к вам обращаться и какой ваш номер телефона для связи?",
    "Клиент: Даниил 89000000000",
]


class BadDateLLMExtractor:
    async def generate(self, prompt: str) -> str:
        return '{"colors":[],"delivery_date":"2023-10-25"}'


def test_screenshot_pickup_order_extracts_roses_and_is_ready_for_admin():
    state = extract_order_state(SCREENSHOT_MESSAGES, today=date(2026, 8, 9))

    assert state.budget == 7500
    assert "розы" in state.colors
    assert state.fulfillment_type == "pickup"
    assert state.delivery_date == "2026-08-10"
    assert state.delivery_time == "18:00"
    assert state.sender_name == "Даниил"
    assert state.sender_phone == "89000000000"


@pytest.mark.asyncio
async def test_llm_extractor_cannot_override_deterministic_relative_date_with_stale_iso():
    state = await extract_order_state_with_llm(
        BadDateLLMExtractor(),
        SCREENSHOT_MESSAGES,
        company_profile=load_company_profile("amelia_flowers"),
        today=date(2026, 8, 9),
        timezone_name="Europe/Kaliningrad",
    )

    assert state.delivery_date == "2026-08-10"
    assert "розы" in state.colors


@pytest.mark.asyncio
async def test_screenshot_pickup_flow_builds_admin_request(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="dummy")
    for message in SCREENSHOT_MESSAGES:
        repo.add_message(client_id=client.id, direction="in" if message.startswith("Клиент:") else "out", text=message.split(": ", 1)[1])

    card = await update_active_order_from_messages_with_optional_llm(
        repo,
        settings=Settings(llm_extractor_enabled=False),
        llm=BadDateLLMExtractor(),
        client_id=client.id,
        recent_messages=SCREENSHOT_MESSAGES,
        company_profile=load_company_profile("amelia_flowers"),
    )
    active_order = repo.get_active_order(client_id=client.id)

    assert card.is_ready_for_admin_request() is True
    assert active_order is not None
    text = build_admin_order_request_if_needed(repo, order=active_order, client_label="@dummy / 123")
    assert text is not None
    assert "Новая заявка" in text
    assert "розы" in text
    assert "2026-08-10" in text
