from amelia_manager.prompts import build_manager_prompt
from amelia_manager.risk import RiskLevel


def test_prompt_tells_manager_not_to_promise_photos_unless_requested():
    prompt = build_manager_prompt(
        client_summary="Клиент выбрал светлый букет до 4000 ₽, доставка 8 августа 13:15 на Сергеева 2.",
        recent_messages=["Клиент: открытка не нужна"],
        stage="bouquet_selection",
        risk_level=RiskLevel.LOW,
    )

    assert "Не выдумывай наличие, цены, сроки, фото" in prompt


def test_prompt_requires_contact_details_before_order_is_considered_ready():
    prompt = build_manager_prompt(
        client_summary="Есть бюджет, адрес, дата и предпочтения по цветам.",
        recent_messages=["Клиент: гортензию можно, открытка не нужна"],
        stage="delivery_details",
        risk_level=RiskLevel.LOW,
    )

    assert "имя и телефон отправителя" in prompt
    assert "имя и телефон получателя" in prompt
    assert "Не закрывай заказ" in prompt
