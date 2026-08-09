from amelia_manager.order_state import extract_order_state


def test_extracts_budget_from_order_phrase_na_amount_and_standalone_after_budget_prompt():
    state = extract_order_state(
        [
            "Клиент: Хотел бы заказать букет для девушки на 15000",
            "Менеджер: сориентируйте по бюджету — в пределах 15000 ₽ или другая сумма?",
            "Клиент: 15000",
        ]
    )

    assert state.budget == 15000
