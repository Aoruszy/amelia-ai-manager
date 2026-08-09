from datetime import date

import pytest

from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.company_profile import load_company_profile
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.llm_client import LLMError
from amelia_manager.order_card import OrderCard
from amelia_manager.order_extractor import extract_order_state_with_llm, looks_like_address
from amelia_manager.order_request import format_admin_order_request
from amelia_manager.order_state import extract_order_state
from amelia_manager.telegram_runtime import update_active_order_from_messages_with_llm


class BadAddressLLM:
    async def generate(self, prompt: str) -> str:
        return '{"fulfillment_type":"delivery","budget":7000,"address":"Хочу букет до 7000"}'


class FailingLLM:
    async def generate(self, prompt: str) -> str:
        raise LLMError("boom")


def ready_pickup_card(delivery_date: str) -> OrderCard:
    return OrderCard(
        budget=7500,
        colors=["розы"],
        fulfillment_type="pickup",
        delivery_date=delivery_date,
        delivery_time="18:00",
        sender_name="Даниил",
        sender_phone="89990000001",
    )


def test_client_summary_formats_iso_date_as_tomorrow_in_profile_timezone(monkeypatch):
    import amelia_manager.date_formatting as date_formatting

    monkeypatch.setattr(date_formatting, "_today_in_timezone", lambda timezone_name: date(2026, 8, 9))

    text = format_client_order_summary(
        ready_pickup_card("2026-08-10"),
        company_profile=load_company_profile("amelia_flowers"),
    )

    assert "• Время: завтра 18:00" in text
    assert "2026-08-10" not in text


def test_client_summary_formats_iso_date_as_russian_month_day(monkeypatch):
    import amelia_manager.date_formatting as date_formatting

    monkeypatch.setattr(date_formatting, "_today_in_timezone", lambda timezone_name: date(2026, 8, 9))

    text = format_client_order_summary(
        ready_pickup_card("2026-08-12"),
        company_profile=load_company_profile("amelia_flowers"),
    )

    assert "• Время: 12 августа 18:00" in text
    assert "2026-08-12" not in text


def test_admin_past_date_warning_uses_profile_timezone(monkeypatch):
    import amelia_manager.date_formatting as date_formatting

    monkeypatch.setattr(date_formatting, "_today_in_timezone", lambda timezone_name: date(2026, 8, 9))

    text = format_admin_order_request(
        order_id=1,
        client_label="@dummy / 123",
        card=ready_pickup_card("2026-08-08"),
        company_profile=load_company_profile("amelia_flowers"),
    )

    assert "2026-08-08 ⚠️ дата в прошлом" in text


def test_admin_request_does_not_mark_same_profile_day_as_past(monkeypatch):
    import amelia_manager.date_formatting as date_formatting

    monkeypatch.setattr(date_formatting, "_today_in_timezone", lambda timezone_name: date(2026, 8, 9))

    text = format_admin_order_request(
        order_id=1,
        client_label="@dummy / 123",
        card=ready_pickup_card("2026-08-09"),
        company_profile=load_company_profile("amelia_flowers"),
    )

    assert "дата в прошлом" not in text


def test_address_validator_accepts_real_addresses_from_llm_live_path():
    assert looks_like_address("Ленинский проспект 12") is True
    assert looks_like_address("Гайдара 173") is True
    assert looks_like_address("Сергеева, 61") is True
    assert looks_like_address("ул. Озерная 7") is True
    assert looks_like_address("улица Гагарина 3") is True


def test_address_extraction_handles_privizite_and_inflected_street_word():
    state = extract_order_state(["Клиент: Привезите на улицу Гагарина 3"], today=date(2026, 8, 9))

    assert state.fulfillment_type == "delivery"
    assert state.address == "улица Гагарина 3"


def test_budget_delivery_phrases_are_not_misclassified_as_address():
    for text in (
        "Хочу букет до 7000, нужна доставка",
        "до 3000 с доставкой",
        "нужен букет до 5000 доставка",
        "бюджет 4000, доставка",
    ):
        state = extract_order_state([f"Клиент: {text}"], today=date(2026, 8, 9))

        assert state.fulfillment_type == "delivery"
        assert state.address is None, text


def test_complex_address_forms_are_llm_responsibility_in_regex_degraded_mode():
    for text in (
        "Доставка Гайдара 173, завтра 11:00",
        "Доставка, ул. Озерная 7, 8 сентября к 10:00",
    ):
        state = extract_order_state([f"Клиент: {text}"], today=date(2026, 8, 9))

        assert state.fulfillment_type == "delivery"
        assert state.address is None, text


def test_address_validator_rejects_budget_date_time_and_phone_noise():
    for value in (
        "Хочу букет до 7000",
        "до 3000",
        "бюджет 4000",
        "Ленинский проспект 12 завтра 14:00",
        "улица Гагарина 3 89990000001",
        "8 сентября к 10:00",
    ):
        assert looks_like_address(value) is False, value


@pytest.mark.asyncio
async def test_llm_address_is_validated_before_merge():
    state = await extract_order_state_with_llm(
        BadAddressLLM(),
        ["Клиент: Хочу букет до 7000, нужна доставка"],
        today=date(2026, 8, 9),
    )

    assert state.fulfillment_type == "delivery"
    assert state.budget == 7000
    assert state.address is None


@pytest.mark.asyncio
async def test_llm_failure_complex_address_degrades_to_missing_address_and_bot_asks_again(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="dummy")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard(
            budget=6000,
            colors=["розы"],
            fulfillment_type="delivery",
            delivery_date="2026-08-10",
            delivery_time="11:00",
            sender_name="Даниил",
            sender_phone="89990000001",
            recipient_name="Ольга",
            recipient_phone="89990000002",
            payment_method="transfer",
        ),
    )

    card = await update_active_order_from_messages_with_llm(
        repo,
        llm=FailingLLM(),
        client_id=client.id,
        recent_messages=["Клиент: Доставка Гайдара 173, завтра 11:00"],
    )
    action = await ConversationEngine(FailingLLM()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: Доставка Гайдара 173, завтра 11:00"],
        stage="order_in_progress",
        order_card=card,
    )

    assert card.address is None
    assert card.is_ready_for_admin_request() is False
    assert "адрес доставки" in action.messages[0].lower()
