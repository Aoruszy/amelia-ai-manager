from amelia_manager.conversation_engine import _format_order_card_context
from amelia_manager.order_card import OrderCard


def test_order_card_context_includes_profile_custom_fields():
    context = _format_order_card_context(
        OrderCard(custom_fields={"service": "чистка зубов", "patient_name": "Ирина"})
    )

    assert "service: чистка зубов" in context
    assert "patient_name: Ирина" in context
