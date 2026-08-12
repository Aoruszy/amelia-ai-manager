from __future__ import annotations

from dataclasses import dataclass
import re

from amelia_manager.company_profile import CompanyProfile


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


def check_reply_safety(
    reply: str,
    *,
    stock_context: str | None = None,
    company_profile: CompanyProfile | None = None,
) -> SafetyResult:
    normalized = reply.lower().replace("ё", "е")
    reasons: list[str] = []

    if any(pattern in normalized for pattern in _IDENTITY_PATTERNS):
        reasons.append("identity_disclosure")
    stock_promise = _has_stock_promise(normalized)
    if stock_promise and not _stock_promise_supported_by_context(normalized, stock_context):
        reasons.append("unverified_stock_promise")
    if _contradicts_unavailable_stock(normalized, stock_context):
        reasons.append("stock_context_contradiction")
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
    if _has_unsupported_price_quote(normalized, stock_context, company_profile=company_profile):
        reasons.append("unsupported_price_quote")

    return SafetyResult(is_safe=not reasons, reasons=reasons)


def _has_stock_promise(reply: str) -> bool:
    if any(pattern in reply for pattern in _STOCK_PROMISE_PATTERNS):
        return True
    for match in re.finditer(r"\bв\s+наличии\b", reply):
        before = reply[max(0, match.start() - 32):match.start()]
        if re.search(r"\b(?:уточн\w*|провер\w*|посмотр\w*|узна\w*)[\s,]+(?:что\s+)?(?:сейчас\s+)?$", before):
            continue
        return True
    return False


def _stock_promise_supported_by_context(reply: str, stock_context: str | None) -> bool:
    if not stock_context:
        return False
    available = []
    for line in stock_context.lower().replace("ё", "е").splitlines():
        match = re.search(r"-\s*([^—-]+)\s*[—-]\s*(?!нет\b)(.+)", line)
        if match:
            available.append(match.group(1).strip())
    return any(item and item in reply for item in available)


def _contradicts_unavailable_stock(reply: str, stock_context: str | None) -> bool:
    if not stock_context:
        return False
    unavailable = []
    for line in stock_context.lower().replace("ё", "е").splitlines():
        match = re.search(r"-\s*([^—-]+)\s*[—-]\s*нет\b", line)
        if match:
            unavailable.append(match.group(1).strip())
    if not unavailable:
        return False
    promises_availability = _has_stock_promise(reply)
    if not promises_availability:
        return False
    return any(item and item in reply for item in unavailable)


def _has_unsupported_price_quote(
    reply: str,
    stock_context: str | None,
    *,
    company_profile: CompanyProfile | None = None,
) -> bool:
    price_quotes = []
    for match in re.finditer(r"\b(\d[\d ]{2,})\s*(?:₽|руб|р\b)", reply):
        window = reply[max(0, match.start() - 48): match.end() + 48]
        if re.search(r"\b(?:сто\w*|цен\w*|за\s+штук\w*|за\s+букет|обойд\w*|выйд\w*)\b", window):
            if _is_approximate_bouquet_estimate(reply, window):
                continue
            price_quotes.append(match.group(1).replace(" ", ""))
    if not price_quotes:
        return False
    allowed_prices = set()
    if stock_context:
        allowed_prices = {
            match.group(1).replace(" ", "")
            for match in re.finditer(r"\b(\d[\d ]{2,})\s*(?:₽|руб|р\b)", stock_context.lower().replace("ё", "е"))
        }
    if company_profile is not None:
        allowed_prices.update(
            str(value)
            for value in (
                company_profile.delivery_city_price,
                company_profile.free_delivery_from,
            )
            if value is not None
        )
    return any(price not in allowed_prices for price in price_quotes)


def _is_approximate_bouquet_estimate(reply: str, window: str) -> bool:
    if "букет" not in reply:
        return False
    if not re.search(r"\b(?:обойд\w*|выйд\w*|сто\w*)\b", window):
        return False
    has_approx_marker = re.search(r"\b(?:примерно|около|ориентировочно|порядка|в\s+районе)\b", window)
    has_range_marker = re.search(r"\b\d[\d ]{2,}\s*[–—-]\s*\d[\d ]{2,}\s*(?:₽|руб|р\b)", window)
    return bool(has_approx_marker or has_range_marker)
