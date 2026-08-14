from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from amelia_manager.company_profile import CompanyProfile, load_company_profile


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskCategory(StrEnum):
    NONE = "none"
    COMPLAINT_REFUND = "complaint_refund"
    DISCOUNT = "discount"
    OUT_OF_AREA_DELIVERY = "out_of_area_delivery"
    CUSTOM_ORDER = "custom_order"
    STOCK_UNCERTAINTY = "stock_uncertainty"
    CONVERSATION_CONFLICT = "conversation_conflict"
    HUMAN_MANAGER_REQUEST = "human_manager_request"
    PAYMENT_CONFIRMATION_WITHOUT_MANAGER = "payment_confirmation_without_manager"
    GUARANTEE_REQUEST = "guarantee_request"
    SENSITIVE_OCCASION = "sensitive_occasion"


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    category: RiskCategory = RiskCategory.NONE
    matched: str | None = None


_CATEGORY_PATTERNS: tuple[tuple[RiskCategory, RiskLevel, tuple[re.Pattern[str], ...]], ...] = (
    (
        RiskCategory.COMPLAINT_REFUND,
        RiskLevel.HIGH,
        (
            re.compile(r"\bжалоб\w*\b"),
            re.compile(r"\bпожаловаться\b"),
            re.compile(r"\bпожалуюсь\b"),
            re.compile(r"\bвозврат\w*\b"),
            re.compile(r"\bверн(?:ите|уть|и)\s+деньги\b"),
            re.compile(r"\bпривезли\s+не\s+то\b"),
            re.compile(r"\bне\s+тот\s+букет\b"),
            re.compile(r"\bобман\w*\b"),
            re.compile(r"\bужас\b"),
            re.compile(r"\bужасн(?:ый|ая|ое|ые)\b"),
        ),
    ),
    (
        RiskCategory.CONVERSATION_CONFLICT,
        RiskLevel.HIGH,
        (
            re.compile(r"\bбред\b"),
            re.compile(r"\bерунда\b"),
            re.compile(r"\bчто\s+вы\s+мне\s+пиш(?:ете|ите)\b"),
        ),
    ),
    (
        RiskCategory.HUMAN_MANAGER_REQUEST,
        RiskLevel.HIGH,
        (
            re.compile(r"\b(?:позовите|позови|пригласите|пригласи|подключите|подключи)\s+(?:жив\w+\s+)?менеджер\w*\b"),
            re.compile(r"\b(?:нужен|нужна|хочу)\s+(?:жив\w+\s+)?менеджер\w*\b"),
        ),
    ),
    (
        RiskCategory.PAYMENT_CONFIRMATION_WITHOUT_MANAGER,
        RiskLevel.HIGH,
        (
            re.compile(r"\b(?:я\s+)?(?:перев[её]л|перевела|оплатил|оплатила)\w*\b"),
            re.compile(r"\bвс[её]\s+оплачен\w*\b"),
            re.compile(r"\bподтвердите\s+заказ\b"),
        ),
    ),
    (
        RiskCategory.CUSTOM_ORDER,
        RiskLevel.HIGH,
        (
            re.compile(r"\bсвадеб\w*\b"),
            re.compile(r"\bсвадьб\w*\b"),
            re.compile(r"\bкорпоратив\w*\b"),
            re.compile(r"\bюр\.?\s*лиц\w*\b"),
            re.compile(r"\b\d{2,}\s+букет\w*\b"),
            re.compile(r"\bоформление\s+зала\b"),
        ),
    ),
    (
        RiskCategory.DISCOUNT,
        RiskLevel.MEDIUM,
        (
            re.compile(r"\bскидк\w*\b"),
            re.compile(r"\bскинуть\s+цену\b"),
            re.compile(r"\bподешевле\b"),
            re.compile(r"\bдешевле\b"),
            re.compile(r"\bдорог(?:о|овато|ой|ая|ие)\b"),
            re.compile(r"\bцена\s+кусается\b"),
        ),
    ),
    (
        RiskCategory.OUT_OF_AREA_DELIVERY,
        RiskLevel.MEDIUM,
        (
            re.compile(r"\bза\s+город\b"),
            re.compile(r"\bв\s+область\b"),
            re.compile(r"\bпосле\s+22(?::00)?\b"),
            re.compile(r"\bпосле\s+десяти\b"),
            re.compile(r"\bночью\b"),
            re.compile(r"\bсрочно\s+прям\s+сейчас\b"),
            re.compile(r"\bточно\s+к\b"),
        ),
    ),
    (
        RiskCategory.STOCK_UNCERTAINTY,
        RiskLevel.MEDIUM,
        (
            re.compile(r"\bв\s+наличии\b"),
            re.compile(r"\bточно\s+есть\b"),
        ),
    ),
    (
        RiskCategory.GUARANTEE_REQUEST,
        RiskLevel.MEDIUM,
        (
            re.compile(r"\bгарантир\w*\b"),
            re.compile(r"\bточно\s+буд\w*\b"),
        ),
    ),
    (
        RiskCategory.SENSITIVE_OCCASION,
        RiskLevel.MEDIUM,
        (
            re.compile(r"\bпохорон\w*\b"),
            re.compile(r"\bтраур\w*\b"),
            re.compile(r"\bвенок\b"),
            re.compile(r"\bсоболезн\w*\b"),
        ),
    ),
)


def assess_risk(text: str, *, company_profile: CompanyProfile | None = None) -> RiskAssessment:
    normalized = text.lower().replace("ё", "е")
    profile = company_profile or load_company_profile("amelia_flowers")
    for term in profile.stock_terms:
        term_pattern = re.escape(term.lower().replace("ё", "е"))
        if re.search(rf"\b{term_pattern}\w*\b", normalized):
            return RiskAssessment(level=RiskLevel.MEDIUM, category=RiskCategory.STOCK_UNCERTAINTY, matched=term)
    for category, level, patterns in _CATEGORY_PATTERNS:
        for pattern in patterns:
            match = pattern.search(normalized)
            if match:
                return RiskAssessment(level=level, category=category, matched=match.group(0))
    return RiskAssessment(level=RiskLevel.LOW)


def classify_risk(text: str) -> RiskLevel:
    return assess_risk(text).level
