from __future__ import annotations

from enum import StrEnum


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_HIGH_RISK_KEYWORDS = (
    "жалоб",
    "пожаловаться",
    "пожалуюсь",
    "возврат",
    "верните деньги",
    "привезли не то",
    "не тот букет",
    "ужас",
    "обман",
    "скидк",
    "бред",
    "ерунда",
    "что вы мне пиш",
    "вы мне пишите",
    "свадеб",
    "свадьб",
    "корпоратив",
    "юрлиц",
    "40 букет",
    "оформление зала",
)

_MEDIUM_RISK_KEYWORDS = (
    "за город",
    "в область",
    "область",
    "после 22",
    "после десяти",
    "ночью",
    "срочно прям сейчас",
    "точно к",
)

_LOW_RISK_KEYWORDS = (
    "аноним",
    "букет",
    "цветы",
    "роз",
    "доставка сегодня",
)


def classify_risk(text: str) -> RiskLevel:
    normalized = text.lower().replace("ё", "е")

    if any(keyword in normalized for keyword in _HIGH_RISK_KEYWORDS):
        return RiskLevel.HIGH
    if any(keyword in normalized for keyword in _MEDIUM_RISK_KEYWORDS):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
