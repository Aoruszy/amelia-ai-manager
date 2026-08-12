from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_prompt_includes_andrey_style_behavior_rules_for_florist():
    prompt = build_manager_prompt(
        client_summary="",
        recent_messages=["Клиент: Хочу цветы купить"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
    )

    assert "Если клиент задал прямой вопрос — сначала ответь на него" in prompt
    assert "без анкеты" in prompt
    assert "только один недостающий шаг" in prompt
    assert "Если поле уже есть" in prompt
    assert "меняй начало и структуру" in prompt


def test_prompt_includes_florist_antimistakes_and_escalation_rules():
    prompt = build_manager_prompt(
        client_summary="",
        recent_messages=["Клиент: Есть пионы?"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
    )

    assert "Не выдумывай наличие" in prompt
    assert "Сергеева, 61 — это адрес самовывоза" in prompt
    assert "статус оформленного заказа" in prompt
    assert "редкие цветы" in prompt
    assert "Подключается менеджер Алина" in prompt
