from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SafetyResult:
    is_safe: bool
    reasons: list[str]


_IDENTITY_PATTERNS = (
    "я ai",
    "я ии",
    "я бот",
    "ai-бот",
    "ии-бот",
    "искусственный интеллект",
    "я модель",
)

_STOCK_PROMISE_PATTERNS = (
    "точно есть",
    "100% есть",
    "сто процентов есть",
    "в наличии",
    "есть в наличии",
)

_EXACT_DELIVERY_PATTERNS = (
    "гарантирую доставку ровно",
    "точно доставим ровно",
    "без задержек",
)

_UNSUPPORTED_PHOTO_PROMISE_PATTERNS = (
    "пришлю фото",
    "отправлю фото",
    "скину фото",
    "фото сборки",
)

_UNSUPPORTED_HANDOFF_PROMISE_PATTERNS = (
    "уточню у флориста",
    "уточню наличие",
    "скоро вернусь",
)

_UNSUPPORTED_PAYMENT_CONFIRMATION_PATTERNS = (
    "заказ подтвержден",
    "оплату по сбп зафиксировала",
    "оплату зафиксировала",
    "оплата зафиксирована",
    "передам курьеру",
    "передаю курьеру",
    "букет соберу",
)


def check_reply_safety(reply: str) -> SafetyResult:
    normalized = reply.lower().replace("ё", "е")
    reasons: list[str] = []

    if any(pattern in normalized for pattern in _IDENTITY_PATTERNS):
        reasons.append("identity_disclosure")
    if any(pattern in normalized for pattern in _STOCK_PROMISE_PATTERNS):
        reasons.append("unverified_stock_promise")
    if any(pattern in normalized for pattern in _EXACT_DELIVERY_PATTERNS):
        reasons.append("exact_delivery_guarantee")
    if any(pattern in normalized for pattern in _UNSUPPORTED_PHOTO_PROMISE_PATTERNS):
        reasons.append("unsupported_photo_promise")
    if any(pattern in normalized for pattern in _UNSUPPORTED_HANDOFF_PROMISE_PATTERNS):
        reasons.append("unsupported_handoff_promise")
    if any(pattern in normalized for pattern in _UNSUPPORTED_PAYMENT_CONFIRMATION_PATTERNS):
        reasons.append("payment_confirmation_without_manager")
    if re.search(r"достав\w*[^\n.]{0,80}сергеева\s*,?\s*61", normalized):
        reasons.append("shop_address_as_delivery")
    if "самовывоз" in normalized and "получател" in normalized and ("телефон" in normalized or "номер" in normalized):
        reasons.append("pickup_recipient_question")

    return SafetyResult(is_safe=not reasons, reasons=reasons)
