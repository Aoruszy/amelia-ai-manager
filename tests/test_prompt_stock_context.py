from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_prompt_includes_stock_context_when_provided():
    prompt = build_manager_prompt(
        client_summary="Клиент хочет сине-белый букет",
        recent_messages=["Клиент: хочу с гортензией"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
        stock_context="По наличию на сегодня релевантно:\n- гортензия голубая — 8",
    )

    assert "Актуальное наличие смены" in prompt
    assert "гортензия голубая — 8" in prompt
