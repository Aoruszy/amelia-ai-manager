from amelia_manager.order_card import OrderCard, merge_order_patch, merge_order_state
from amelia_manager.order_state import OrderState


def test_merge_order_state_preserves_existing_fields_when_new_message_is_partial():
    existing = OrderCard(
        budget=5000,
        colors=["синий", "белый"],
        fulfillment_type="pickup",
        delivery_date="today",
        delivery_time="18:00",
        sender_name="Даниил",
        sender_phone="89990000006",
    )

    merged = merge_order_state(existing, OrderState(colors=["синий", "белый"]))

    assert merged.budget == 5000
    assert merged.fulfillment_type == "pickup"
    assert merged.sender_phone == "89990000006"
    assert merged.colors == ["синий", "белый"]


def test_order_card_ready_for_pickup_without_recipient_contacts():
    card = OrderCard(
        budget=5000,
        colors=["синий", "белый"],
        fulfillment_type="pickup",
        delivery_date="today",
        delivery_time="18:00",
        sender_name="Даниил",
        sender_phone="89990000006",
        payment_method="transfer",
    )

    assert card.is_ready_for_admin_request() is True


def test_order_card_ready_for_delivery_requires_address_and_recipient():
    card = OrderCard(
        budget=7000,
        colors=["синий", "белый"],
        fulfillment_type="delivery",
        delivery_date="today",
        delivery_time="18:00",
        address="Гайдара 173",
        sender_name="Даниил",
        sender_phone="89990000007",
        recipient_name="Ольга",
        recipient_phone="89990000008",
        payment_method="card",
    )

    assert card.is_ready_for_admin_request() is True


def test_order_card_delivery_not_ready_without_recipient_phone():
    card = OrderCard(
        budget=7000,
        colors=["синий"],
        fulfillment_type="delivery",
        delivery_date="today",
        delivery_time="18:00",
        address="Гайдара 173",
        sender_name="Даниил",
        sender_phone="89990000007",
    )

    assert card.is_ready_for_admin_request() is False


def test_merge_order_patch_merges_custom_fields_without_dropping_existing_values():
    existing = OrderCard(custom_fields={"service": "венок", "occasion_sensitive": True})

    merged = merge_order_patch(existing, {"custom_fields": {"budget_note": "до 5000"}})

    assert merged.custom_fields == {
        "service": "венок",
        "occasion_sensitive": True,
        "budget_note": "до 5000",
    }
