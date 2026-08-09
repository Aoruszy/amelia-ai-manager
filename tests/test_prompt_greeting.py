from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_prompt_says_not_to_ask_delivery_for_plain_greeting():
    prompt = build_manager_prompt(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Здравствуйте"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
    )

    assert "если клиент только поздоровался" in prompt
    assert "не спрашивай про доставку" in prompt
