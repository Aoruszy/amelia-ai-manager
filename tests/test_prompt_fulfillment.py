from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_prompt_does_not_assume_delivery_when_client_has_not_chosen_fulfillment():
    prompt = build_manager_prompt(
        client_summary="Клиент хочет подарить букет девушке, цвет синий/белый, бюджет 7000.",
        recent_messages=["Клиент: любимый цвет синий и белый, бюджет 7000"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
    )

    assert "не говори про доставку как единственный вариант" in prompt
    assert "доставка или самовывоз" in prompt
    assert "если клиент уже выбрал доставку" in prompt
