from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_prompt_omits_plain_greeting_rules_handled_before_llm():
    prompt = build_manager_prompt(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Здравствуйте"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
    )

    assert "если клиент только поздоровался" not in prompt.lower()
    assert "ответь коротко «Здравствуйте" not in prompt
