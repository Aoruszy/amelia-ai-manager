import pytest

from amelia_manager.company_profile import CompanyProfile
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.order_card import OrderCard


class CapturingLLM:
    def __init__(self):
        self.prompt = None

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return "Да, записываю."


@pytest.mark.asyncio
async def test_engine_passes_company_profile_to_prompt():
    profile = CompanyProfile(
        company_name="Dental Plus",
        manager_name="Марина",
        business_type="clinic",
        city="Калининград",
        tone="спокойный",
        services=["чистка зубов"],
        required_fields={},
        business_rules=["не ставить диагноз по переписке"],
    )
    llm = CapturingLLM()

    await ConversationEngine(llm, company_profile=profile).handle_messages(
        client_summary="",
        recent_messages=["Клиент: Хочу записаться"],
        stage="new_lead",
    )

    assert "Dental Plus" in llm.prompt
    assert "Марина" in llm.prompt
    assert "Amelia Flowers" not in llm.prompt


@pytest.mark.asyncio
async def test_engine_uses_company_profile_in_ready_order_summary():
    profile = CompanyProfile(
        company_name="Cake Lab",
        manager_name="Оля",
        business_type="bakery",
        city="Калининград",
        tone="тёплый",
        services=["торты"],
        required_fields={},
        business_rules=[],
        pickup_address="Ленина, 10",
    )
    card = OrderCard(
        budget=3000,
        colors=["шоколадный"],
        fulfillment_type="pickup",
        delivery_date="tomorrow",
        delivery_time="15:00",
        sender_name="Иван",
        sender_phone="89990000010",
        payment_method="cash",
    )

    action = await ConversationEngine(CapturingLLM(), company_profile=profile).handle_messages(
        client_summary="",
        recent_messages=["Клиент: Оплачу на месте"],
        stage="ordering",
        order_card=card,
    )

    assert "Самовывоз с Ленина, 10" in action.messages[0]
    assert "• Заказ: шоколадный" in action.messages[0]
