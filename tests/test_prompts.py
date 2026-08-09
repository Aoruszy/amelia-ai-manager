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
    assert "не говори, что ты AI" in prompt
    assert "не обещай наличие" in prompt
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
