from amelia_manager.dialogue_eval import DialogueScenario, _evaluate_checks
from amelia_manager.risk import RiskLevel


def test_no_repeated_phrase_flags_same_bot_opening():
    scenario = DialogueScenario(
        "repeat-opening",
        "order_flow",
        [
            "Клиент: Хочу нежный пастельный букет",
            "Менеджер: Тогда ориентируемся на нежный пастельный букет 🌸 Вам удобнее доставка или самовывоз?",
            "Клиент: Самовывоз",
        ],
        structural_checks=("no_repeated_phrase",),
    )

    checks = _evaluate_checks(
        scenario,
        kind="send",
        risk_level=RiskLevel.LOW,
        output="Отлично, тогда ориентируемся на нежный пастельный букет 🌸 На какое число нужен букет?",
    )

    repeated = next(check for check in checks if check["name"] == "no_repeated_phrase")
    assert not repeated["passed"]


def test_no_repeated_phrase_allows_direct_next_question():
    scenario = DialogueScenario(
        "no-repeat-opening",
        "order_flow",
        [
            "Клиент: Хочу нежный пастельный букет",
            "Менеджер: Тогда ориентируемся на нежный пастельный букет 🌸 Вам удобнее доставка или самовывоз?",
            "Клиент: Самовывоз",
        ],
        structural_checks=("no_repeated_phrase",),
    )

    checks = _evaluate_checks(
        scenario,
        kind="send",
        risk_level=RiskLevel.LOW,
        output="Отлично, на какое число нужен букет?",
    )

    repeated = next(check for check in checks if check["name"] == "no_repeated_phrase")
    assert repeated["passed"]
