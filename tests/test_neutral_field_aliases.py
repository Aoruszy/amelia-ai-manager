from amelia_manager.order_card import OrderCard
from amelia_manager.order_state import OrderState


def test_order_card_exposes_neutral_product_field_aliases():
    card = OrderCard(colors=["нежный стиль"], forbidden_flowers=["хризантемы"], postcard_text="Люблю")

    assert card.product_preferences == ["нежный стиль"]
    assert card.excluded_items == ["хризантемы"]
    assert card.note_text == "Люблю"


def test_order_state_exposes_neutral_product_field_aliases():
    state = OrderState(colors=["шоколадный"], forbidden_flowers=["орехи"], postcard_text="без надписи")

    assert state.product_preferences == ["шоколадный"]
    assert state.excluded_items == ["орехи"]
    assert state.note_text == "без надписи"
