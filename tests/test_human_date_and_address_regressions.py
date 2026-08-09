from datetime import date

from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.company_profile import load_company_profile
from amelia_manager.order_card import OrderCard
from amelia_manager.order_request import format_admin_order_request
from amelia_manager.order_state import extract_order_state


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


def test_composite_delivery_address_strips_date_tail_instead_of_dropping_candidate():
    state = extract_order_state(
        ["Клиент: Букет до 6000, доставка на Ленинский проспект 12, завтра к 14:00"],
        today=date(2026, 8, 9),
    )

    assert state.fulfillment_type == "delivery"
    assert state.address == "Ленинский проспект 12"
    assert state.delivery_date == "2026-08-10"
    assert state.delivery_time == "14:00"


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
