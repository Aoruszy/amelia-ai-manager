from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import OrderState


def test_next_step_asks_fulfillment_before_delivery_address():
    state = OrderState(occasion="девушке", budget=7000, colors=["синий", "белый"], delivery_date="today", delivery_time="18:00")

    step = get_next_step(state)

    assert step.code == "ask_when_where"
    assert step.missing == ("fulfillment_type", "address")
    assert "куда" in step.instruction.lower()


def test_next_step_asks_address_only_after_delivery_chosen():
    state = OrderState(fulfillment_type="delivery", budget=7000, colors=["синий"], delivery_date="today", delivery_time="18:00")

    step = get_next_step(state)

    assert step.code == "ask_when_where"
    assert step.missing == ("address",)
    assert "адрес" in step.instruction.lower()


def test_when_where_partial_date_narrows_to_time_and_address_without_when_word():
    state = OrderState(budget=7000, colors=["синий"], fulfillment_type="delivery", delivery_date="2026-08-22")

    step = get_next_step(state)

    assert step.code == "ask_when_where"
    assert step.missing == ("delivery_time", "address")
    assert "когда" not in step.instruction.lower()
    assert "время" in step.instruction.lower()
    assert "адрес" in step.instruction.lower()


def test_when_where_second_empty_attempt_narrows_to_one_field_without_human_review():
    state = OrderState(
        budget=7000,
        colors=["синий"],
        custom_fields={"_asked_groups": {"ask_when_where": True}},
    )

    step = get_next_step(state)

    assert step.code == "ask_when_where"
    assert step.missing == ("fulfillment_type",)
    assert "доставка или самовывоз" in step.instruction.lower()
    assert "адрес" not in step.instruction.lower()


def test_when_where_repeated_partial_pickup_time_gets_direct_reworded_prompt():
    state = OrderState(
        budget=7000,
        colors=["синий"],
        fulfillment_type="pickup",
        delivery_date="2026-08-22",
        custom_fields={"_asked_groups": {"ask_when_where": ("delivery_time",)}},
    )

    step = get_next_step(state)

    assert step.code == "ask_when_where"
    assert step.missing == ("delivery_time",)
    assert "прямо" in step.instruction.lower()
    assert "другими словами" in step.instruction.lower()


def test_when_where_repeated_partial_delivery_time_gets_direct_single_field_prompt():
    state = OrderState(
        budget=7000,
        colors=["синий"],
        fulfillment_type="delivery",
        delivery_date="2026-08-22",
        address="Ленина 5",
        custom_fields={"_asked_groups": {"ask_when_where": ("delivery_time",)}},
    )

    step = get_next_step(state)

    assert step.code == "ask_when_where"
    assert step.missing == ("delivery_time",)
    assert "прямо" in step.instruction.lower()
    assert "другими словами" in step.instruction.lower()
    assert "адрес" not in step.instruction.lower()


def test_when_where_partial_progress_does_not_trigger_repeat_guard():
    state = OrderState(
        budget=7000,
        colors=["синий"],
        fulfillment_type="delivery",
        delivery_date="2026-08-22",
        custom_fields={"_asked_groups": {"ask_when_where": ("fulfillment_type", "delivery_date", "delivery_time", "address")}},
    )

    step = get_next_step(state)

    assert step.missing == ("delivery_time", "address")
    assert "другими словами" not in step.instruction.lower()


def test_contacts_repeated_partial_group_gets_direct_sender_prompt():
    state = OrderState(
        budget=7000,
        colors=["синий"],
        fulfillment_type="delivery",
        delivery_date="2026-08-22",
        delivery_time="14:00",
        address="Ленина 5",
        sender_phone="89990000001",
        recipient_name="Мария",
        recipient_phone="89990000002",
        custom_fields={"upsell_offered": True, "_asked_groups": {"ask_contacts": ("sender_name",)}},
    )

    step = get_next_step(state)

    assert step.code == "ask_contacts"
    assert step.missing == ("sender_name",)
    assert "прямо" in step.instruction.lower()


def test_contacts_repeated_partial_recipient_name_gets_direct_single_field_prompt():
    state = OrderState(
        budget=7000,
        colors=["синий"],
        fulfillment_type="delivery",
        delivery_date="2026-08-22",
        delivery_time="14:00",
        address="Ленина 5",
        sender_name="Анна",
        sender_phone="89990000001",
        recipient_phone="89990000002",
        custom_fields={"upsell_offered": True, "_asked_groups": {"ask_contacts": ("recipient_name",)}},
    )

    step = get_next_step(state)

    assert step.code == "ask_contacts"
    assert step.missing == ("recipient_name",)
    assert "прямо" in step.instruction.lower()
    assert "другими словами" in step.instruction.lower()
    assert "телефон" not in step.instruction.lower()


def test_contacts_first_partial_recipient_prompt_is_not_direct_interrogation():
    state = OrderState(
        budget=7000,
        colors=["синий"],
        fulfillment_type="delivery",
        delivery_date="2026-08-22",
        delivery_time="14:00",
        address="Ленина 5",
        sender_name="Анна",
        sender_phone="89990000001",
        recipient_phone="89990000002",
        custom_fields={"upsell_offered": True},
    )

    step = get_next_step(state)

    assert step.code == "ask_contacts"
    assert step.missing == ("recipient_name",)
    assert "прямо" not in step.instruction.lower()
    assert "другими словами" not in step.instruction.lower()


def test_action_patch_merges_nested_asked_groups_without_erasing_previous_group():
    from amelia_manager.conversation_engine import _merge_action_patch

    merged = _merge_action_patch(
        {"custom_fields": {"_asked_groups": {"ask_when_where": ("delivery_time",)}}},
        {"custom_fields": {"_asked_groups": {"ask_contacts": ("sender_name",)}}},
    )

    assert merged["custom_fields"]["_asked_groups"] == {
        "ask_when_where": ("delivery_time",),
        "ask_contacts": ("sender_name",),
    }


def test_pickup_when_where_group_does_not_require_address():
    state = OrderState(budget=7000, colors=["синий"], fulfillment_type="pickup", delivery_date="2026-08-22")

    step = get_next_step(state)

    assert step.code == "ask_when_where"
    assert step.missing == ("delivery_time",)
    assert "адрес" not in step.instruction.lower()


def test_delivery_contacts_group_asks_missing_sender_and_recipient_together():
    state = OrderState(
        budget=7000,
        colors=["синий"],
        fulfillment_type="delivery",
        delivery_date="2026-08-22",
        delivery_time="14:00",
        address="Ленина 5",
        custom_fields={"upsell_offered": True},
    )

    step = get_next_step(state)

    assert step.code == "ask_contacts"
    assert step.missing == ("sender_name", "sender_phone", "recipient_name", "recipient_phone")


def test_pickup_contacts_group_needs_only_sender():
    state = OrderState(
        budget=7000,
        colors=["синий"],
        fulfillment_type="pickup",
        delivery_date="2026-08-22",
        delivery_time="14:00",
        custom_fields={"upsell_offered": True},
    )

    step = get_next_step(state)

    assert step.code == "ask_contacts"
    assert step.missing == ("sender_name", "sender_phone")


def test_next_step_after_address_and_contacts_asks_anonymous_or_payment_not_handoff():
    state = OrderState(
        fulfillment_type="delivery",
        delivery_date="today",
        delivery_time="18:00",
        address="Гайдара 173",
        sender_name="Даниил",
        sender_phone="89990000007",
        recipient_name="Ольга",
        recipient_phone="89990000008",
        budget=7000,
        colors=["синий", "белый"],
    )

    step = get_next_step(state)

    assert step.code == "ask_anonymous_or_payment"
    assert "ответственному менеджеру" not in step.instruction.lower()
