from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_prompt_contains_soft_sales_style_without_pushiness():
    prompt = build_manager_prompt(
        client_summary="",
        recent_messages=["Клиент: хочу букет девушке до 5000"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
    )

    assert "мягко помогай выбрать" in prompt
    assert "не дави" in prompt
    assert "дороже и романтичнее" in prompt
