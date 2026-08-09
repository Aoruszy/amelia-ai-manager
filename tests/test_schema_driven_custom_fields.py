import pytest

from amelia_manager.company_profile import BusinessField, CompanyProfile
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_extractor import extract_order_state_with_llm
from amelia_manager.telegram_runtime import update_active_order_from_messages_with_llm


class CapturingLLM:
    def __init__(self, response: str):
        self.response = response
        self.prompt = ""

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return self.response


def clinic_profile() -> CompanyProfile:
    return CompanyProfile(
        company_name="Dental Plus",
        manager_name="Марина",
        business_type="clinic",
        city="Калининград",
        tone="спокойный",
        services=["чистка зубов", "лечение"],
        required_fields={
            "appointment": [
                BusinessField("service", "услуга"),
                BusinessField("date", "дата"),
                BusinessField("time", "время"),
                BusinessField("patient_name", "имя пациента"),
                BusinessField("customer_phone", "телефон"),
            ]
        },
        business_rules=["не ставить диагноз по переписке"],
    )


@pytest.mark.asyncio
async def test_llm_extractor_uses_company_profile_custom_fields_without_florist_regex():
    llm = CapturingLLM(
        '{"custom_fields":{"service":"чистка зубов","patient_name":"Ирина"},'
        '"delivery_date":"12 августа","delivery_time":"15:00","sender_phone":"89990000001"}'
    )

    state = await extract_order_state_with_llm(
        llm,
        ["Клиент: хочу записаться на чистку зубов 12 августа в 15:00, Ирина 89990000001"],
        company_profile=clinic_profile(),
    )

    assert state.custom_fields == {"service": "чистка зубов", "patient_name": "Ирина"}
    assert state.delivery_date == "2026-08-12"
    assert state.delivery_time == "15:00"
    assert "service" in llm.prompt
    assert "patient_name" in llm.prompt
    assert "colors" not in llm.prompt
    assert "forbidden_flowers" not in llm.prompt


@pytest.mark.asyncio
async def test_runtime_merges_profile_custom_fields_into_active_card(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    llm = CapturingLLM('{"custom_fields":{"service":"чистка зубов","patient_name":"Ирина"}}')

    card = await update_active_order_from_messages_with_llm(
        repo,
        llm=llm,
        client_id=client.id,
        recent_messages=["Клиент: хочу записаться на чистку зубов, Ирина"],
        company_profile=clinic_profile(),
    )

    assert card.custom_fields == {"service": "чистка зубов", "patient_name": "Ирина"}
