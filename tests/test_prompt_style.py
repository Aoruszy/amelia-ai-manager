from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_prompt_enforces_single_manager_human_style():
    prompt = build_manager_prompt(
        client_summary="Новый клиент",
        recent_messages=["Клиент: Добрый вечер! Нужен букет до 4 тысяч"],
        stage="new_lead",
        risk_level=RiskLevel.LOW,
    )

    assert "Говори от первого лица как один менеджер" in prompt
    assert "Вместо корпоративного «поможем" in prompt
    assert "Доставку/самовывоз" in prompt
    assert "только один недостающий шаг" in prompt
    assert "не задавай больше двух вопросов" not in prompt
