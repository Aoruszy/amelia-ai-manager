import pytest

from amelia_manager.company_profile import BusinessField, CompanyProfile
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.order_card import OrderCard
from amelia_manager.order_policy import get_next_step


class CapturingLLM:
    def __init__(self):
        self.prompt = ""

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return "Подскажите, пожалуйста, имя пациента."


def clinic_profile() -> CompanyProfile:
    return CompanyProfile(
        company_name="Dental Plus",
        manager_name="Марина",
        business_type="clinic",
        city="Калининград",
        tone="спокойный",
        required_fields={
            "appointment": [
                BusinessField("service", "услуга"),
                BusinessField("date", "дата"),
                BusinessField("time", "время"),
                BusinessField("patient_name", "имя пациента"),
                BusinessField("customer_phone", "телефон"),
            ]
        },
    )


def test_profile_next_step_asks_first_missing_custom_field():
    step = get_next_step(
        OrderCard(custom_fields={"service": "чистка зубов"}, delivery_date="12 августа", delivery_time="15:00"),
        company_profile=clinic_profile(),
        case_type="appointment",
    )

    assert step.code == "ask_patient_name"
    assert "имя пациента" in step.instruction
    assert "букет" not in step.instruction.lower()


@pytest.mark.asyncio
async def test_engine_uses_profile_next_step_instruction_for_non_florist():
    llm = CapturingLLM()

    await ConversationEngine(llm, company_profile=clinic_profile()).handle_messages(
        client_summary="",
        recent_messages=["Клиент: хочу записаться на чистку зубов 12 августа 15:00"],
        stage="new_lead",
        order_card=OrderCard(custom_fields={"service": "чистка зубов"}, delivery_date="12 августа", delivery_time="15:00"),
    )

    assert "Следующий обязательный шаг" in llm.prompt
    assert "имя пациента" in llm.prompt
    assert "букет" not in llm.prompt.lower()
