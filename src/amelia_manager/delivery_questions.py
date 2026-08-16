from __future__ import annotations

import re

from amelia_manager.company_profile import CompanyProfile, load_company_profile


_PRICE_WORD_RE = re.compile(r"\b(?:дорог\w*|цен\w*|сто\w*|сколько|почем|платн\w*)\b")
_DELIVERY_RE = re.compile(r"\bдоставк\w*\b")
_OUT_OF_AREA_RE = re.compile(
    r"\b(?:за\s+город|в\s+область|ночью|после\s+22(?::00)?|после\s+десяти)\b"
)
_DIRECTION_RE = re.compile(r"\b(?:в|до)\s+([а-яa-z][а-яa-z\-]{3,})\b")
_CITY_SCOPE_RE = re.compile(r"\b(?:по\s+городу|в\s+городе|в\s+пределах\s+города)\b")
_NON_DIRECTION_WORDS = {
    # Days and relative dates.
    "понедельник",
    "понедельнику",
    "вторник",
    "вторнику",
    "среду",
    "среда",
    "четверг",
    "четвергу",
    "пятницу",
    "пятница",
    "субботу",
    "суббота",
    "воскресенье",
    "сегодня",
    "завтра",
    "послезавтра",
    # Times of day. "ночью" is intentionally not here: it is an out-of-hours marker.
    "утро",
    "утра",
    "день",
    "дня",
    "вечер",
    "вечера",
    "ночь",
    # In-city/address context, not geography outside the city.
    "центр",
    "центра",
    "подъезд",
    "подъезда",
    "офис",
    "офиса",
    "район",
    "района",
    "дом",
    "дома",
    "квартиру",
    "квартира",
    "подарок",
    "подарка",
}


def normalize_question_text(text: str) -> str:
    return text.lower().replace("ё", "е")


def is_delivery_price_question(text: str) -> bool:
    normalized = normalize_question_text(text)
    return bool(_DELIVERY_RE.search(normalized) and _PRICE_WORD_RE.search(normalized))


def is_city_delivery_price_question(
    text: str,
    *,
    company_profile: CompanyProfile | None = None,
) -> bool:
    """True when the question can safely use the in-city delivery price fact."""
    if not is_delivery_price_question(text):
        return False
    return not is_out_of_area_delivery_price_question(text, company_profile=company_profile)


def is_out_of_area_delivery_price_question(
    text: str,
    *,
    company_profile: CompanyProfile | None = None,
) -> bool:
    normalized = normalize_question_text(text)
    if not is_delivery_price_question(normalized):
        return False

    profile = company_profile or load_company_profile("amelia_flowers")
    if _OUT_OF_AREA_RE.search(normalized):
        return True
    if _has_city_scope(normalized, profile):
        return False
    return _has_unknown_direction(normalized, profile)


def _has_city_scope(normalized: str, profile: CompanyProfile) -> bool:
    if _CITY_SCOPE_RE.search(normalized):
        return True
    own_city = normalize_question_text(profile.city or "")
    if not own_city:
        return False
    own_city_stem = own_city.rstrip("аеуыиоюяь")
    return bool(re.search(rf"\bпо\s+{re.escape(own_city_stem)}\w*\b", normalized))


def _has_unknown_direction(normalized: str, profile: CompanyProfile) -> bool:
    own_city = normalize_question_text(profile.city or "")
    own_city_stem = own_city.rstrip("аеуыиоюяь")
    for match in _DIRECTION_RE.finditer(normalized):
        destination = _direction_word(match)
        if destination in _NON_DIRECTION_WORDS or destination in {"город", "городу", "городе"}:
            continue
        if own_city and (destination == own_city or (own_city_stem and destination.startswith(own_city_stem))):
            continue
        return True
    return False


def _direction_word(match: re.Match[str]) -> str:
    return match.group(1).strip(" .,!?")
