from amelia_manager.company_profile import BusinessField, CompanyProfile
from amelia_manager.model_decision import ModelDecision
from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_prompt_contains_persona_store_facts_and_safety_rules():
    prompt = build_manager_prompt(
        client_summary="Клиент хочет букет девушке.",
        recent_messages=["Клиент: Привет, нужен букет"],
        stage="bouquet_selection",
        risk_level=RiskLevel.LOW,
    )

    assert "Алина" in prompt
    assert "Amelia Flowers" in prompt
    assert "Калининград" in prompt
    assert "Сергеева 61" in prompt
    assert "Не называй себя AI" in prompt
    assert "Не выдумывай наличие" in prompt
    assert "bouquet_selection" in prompt
    assert "Клиент хочет букет девушке" in prompt


def test_prompt_for_high_risk_tells_manager_to_handoff():
    prompt = build_manager_prompt(
        client_summary="Клиент жалуется на заказ.",
        recent_messages=["Клиент: хочу возврат"],
        stage="human_takeover",
        risk_level=RiskLevel.HIGH,
    )

    assert "HIGH RISK" in prompt
    assert "передай человеку" in prompt.lower()


def test_prompt_describes_model_decision_response_schema_and_confidence_rubric():
    prompt = build_manager_prompt(
        client_summary="Клиент хочет букет.",
        recent_messages=["Клиент: Нужен букет"],
        stage="bouquet_selection",
        risk_level=RiskLevel.LOW,
    )

    assert "Верни только текст сообщения" not in prompt
    for field_name in ModelDecision.model_fields:
        assert field_name in prompt
    assert "0.9–1.0" in prompt
    assert "0.7–0.9" in prompt
    assert "0.5–0.7" in prompt
    assert "ниже 0.5" in prompt


def test_prompt_case_patch_fields_are_generated_from_non_florist_profile_required_fields():
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
                BusinessField("patient_phone", "телефон пациента"),
            ]
        },
    )

    prompt = build_manager_prompt(
        client_summary="Новый клиент",
        recent_messages=["Клиент: хочу записаться на чистку"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
        company_profile=profile,
    )

    assert "service — услуга" in prompt
    assert "date — дата" in prompt
    assert "patient_phone — телефон пациента" in prompt
    assert "budget — бюджет" not in prompt
    assert "delivery_address" not in prompt


def test_prompt_removes_dead_duplicate_and_conflicting_rules():
    prompt = build_manager_prompt(
        client_summary="",
        recent_messages=["Клиент: Хочу букет"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
    )

    assert "не задавай больше двух вопросов" not in prompt
    assert "если клиент только поздоровался" not in prompt.lower()
    assert "не ставь один и тот же" not in prompt
    assert prompt.lower().count("говори от первого лица") == 1
    assert prompt.count("Не переспрашивай поля") == 0


def test_prompt_contains_explicit_priority_hierarchy_for_direct_questions_and_steps():
    prompt = build_manager_prompt(
        client_summary="",
        recent_messages=["Клиент: А сколько доставка?"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
        next_step_instruction="Уточни бюджет одним коротким вопросом.",
    )

    assert "Порядок приоритетов при конфликте правил" in prompt
    assert "1. Безопасность" in prompt
    assert "2. Прямой вопрос клиента" in prompt
    assert "3. Обязательный шаг" in prompt
    assert "4. Один вопрос" in prompt
    assert "шаг переносится" in prompt
    assert "Задай только этот шаг" not in prompt
