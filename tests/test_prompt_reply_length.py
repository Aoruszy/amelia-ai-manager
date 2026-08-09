from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_prompt_tells_model_to_keep_replies_under_400_chars():
    prompt = build_manager_prompt(
        client_summary="",
        recent_messages=["Клиент: Хочу букет"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
    )

    assert "до 400 символов" in prompt
