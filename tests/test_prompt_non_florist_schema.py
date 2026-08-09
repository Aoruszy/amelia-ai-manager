import pytest

from amelia_manager.company_profile import BusinessField, CompanyProfile
from amelia_manager.conversation_engine import ConversationEngine


class CapturingLLM:
    def __init__(self):
        self.prompt = ""

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return "Да, подскажу."


@pytest.mark.asyncio
async def test_non_florist_prompt_uses_profile_schema_without_florist_leakage():
    profile = CompanyProfile(
        company_name="Dental Plus",
        manager_name="Марина",
        business_type="clinic",
        city="Калининград",
        tone="спокойный",
        services=["чистка зубов"],
        required_fields={
            "appointment": [
                BusinessField("service", "услуга"),
                BusinessField("date", "дата"),
                BusinessField("time", "время"),
                BusinessField("patient_name", "имя пациента"),
            ]
        },
        business_rules=["не ставить диагноз по переписке"],
    )
    llm = CapturingLLM()

    await ConversationEngine(llm, company_profile=profile).handle_messages(
        client_summary="",
        recent_messages=["Клиент: хочу записаться на чистку зубов"],
        stage="new_lead",
    )

    assert "Dental Plus" in llm.prompt
    assert "appointment: услуга, дата, время, имя пациента" in llm.prompt
    assert "букет" not in llm.prompt.lower()
    assert "цвет" not in llm.prompt.lower()
    assert "сeргеева" not in llm.prompt.lower()
    assert "Сергеева" not in llm.prompt
