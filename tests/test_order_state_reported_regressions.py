from datetime import date

from amelia_manager.order_state import extract_order_state


def test_budget_understands_thousand_phrases_and_suffixes():
    assert extract_order_state(["Клиент: букет за 15 тысяч"]).budget == 15_000
    assert extract_order_state(["Клиент: букет за пять тысяч"]).budget == 5_000
    assert extract_order_state(["Клиент: букет за 15к"]).budget == 15_000
    assert extract_order_state(["Клиент: букет тысяч на 5"]).budget == 5_000


def test_later_clarified_budget_wins_over_earlier_cap():
    state = extract_order_state(["Клиент: до 5000, но лучше 3000"])

    assert state.budget == 3000


def test_delivery_negation_prefers_pickup_or_none():
    assert extract_order_state(["Клиент: не надо доставку, я сам заберу"]).fulfillment_type == "pickup"
    assert extract_order_state(["Клиент: Не нужна доставка"]).fulfillment_type is None


def test_delivery_address_extracts_prospect_after_delivery_marker():
    state = extract_order_state(["Клиент: доставка на Ленинский проспект 12"])

    assert state.fulfillment_type == "delivery"
    assert state.address == "Ленинский проспект 12"


def test_relative_delivery_dates_resolve_to_iso_with_reference_date():
    assert extract_order_state(["Клиент: доставка сегодня"], today=date(2026, 8, 9)).delivery_date == "2026-08-09"
    assert extract_order_state(["Клиент: доставка завтра"], today=date(2026, 8, 9)).delivery_date == "2026-08-10"


def test_calendar_date_with_year_stays_iso_and_not_budget():
    state = extract_order_state(["Клиент: букет на 8 марта 2026"], today=date(2026, 8, 9))

    assert state.budget is None
    assert state.delivery_date == "2026-03-08"
