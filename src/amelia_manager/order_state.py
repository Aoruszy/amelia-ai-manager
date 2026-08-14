from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class OrderState:
    occasion: str | None = None
    budget: int | None = None
    colors: list[str] = field(default_factory=list)
    forbidden_flowers: list[str] = field(default_factory=list)
    fulfillment_type: str | None = None  # delivery / pickup
    delivery_date: str | None = None
    delivery_time: str | None = None
    address: str | None = None
    sender_name: str | None = None
    sender_phone: str | None = None
    recipient_name: str | None = None
    recipient_phone: str | None = None
    payment_method: str | None = None
    postcard_text: str | None = None
    anonymous: bool | None = None
    photo_report_requested: bool | None = None
    custom_fields: dict[str, Any] = field(default_factory=dict)

    @property
    def product_preferences(self) -> list[str]:
        return self.colors

    @property
    def excluded_items(self) -> list[str]:
        return self.forbidden_flowers

    @property
    def note_text(self) -> str | None:
        return self.postcard_text


def extract_order_state(messages: list[str], *, today: date | None = None, timezone_name: str = "Europe/Kaliningrad") -> OrderState:
    client_messages = [_strip_role(message) for message in messages if _is_client_message(message)]
    text = "\n".join(client_messages).lower().replace("ё", "е")
    context_text = "\n".join(_strip_role(message) for message in messages).lower().replace("ё", "е")
    original = "\n".join(client_messages)
    contacts = _extract_contacts_by_dialog_context(messages)
    recipient_name = contacts.get("recipient_name") or _extract_recipient_name(original)
    recipient_phone = contacts.get("recipient_phone") or _extract_recipient_phone(original)
    sender_name = contacts.get("sender_name") or _extract_sender_name(original, exclude_phone=recipient_phone)
    sender_phone = contacts.get("sender_phone") or _extract_sender_phone(original, exclude_phone=recipient_phone)
    reference_date = today or datetime.now(ZoneInfo(timezone_name)).date()

    return OrderState(
        occasion=_extract_occasion(text),
        budget=_extract_budget(text, context_text=context_text),
        colors=_extract_colors(text),
        forbidden_flowers=_extract_forbidden_flowers(text),
        fulfillment_type=_extract_fulfillment_type(text),
        delivery_date=_extract_delivery_date(context_text, today=reference_date),
        delivery_time=_extract_delivery_time(text),
        address=_extract_address(original),
        sender_name=sender_name,
        sender_phone=sender_phone,
        recipient_name=recipient_name,
        recipient_phone=recipient_phone,
        payment_method=_extract_payment_method(text),
        postcard_text=_extract_postcard_text(text),
        anonymous=_extract_anonymous(text),
        photo_report_requested=_extract_photo_report_requested(text),
    )


def _strip_role(message: str) -> str:
    for prefix in ("Клиент:", "Менеджер:", "Алина:"):
        if message.lower().startswith(prefix.lower()):
            return message[len(prefix):].strip()
    return message.strip()


def _is_client_message(message: str) -> bool:
    lowered = message.lower().strip()
    return lowered.startswith("клиент:") or not (
        lowered.startswith("менеджер:") or lowered.startswith("алина:")
    )


def _extract_occasion(text: str) -> str | None:
    if "девушк" in text:
        return "девушке"
    if "мам" in text:
        return "маме"
    if re.search(r"\bжен(?:е|у|а|ы|ой)\b", text):
        return "жене"
    return None


def _extract_budget(text: str, *, context_text: str | None = None) -> int | None:
    candidates: list[tuple[int, int]] = []

    for match in re.finditer(r"\b(?:тысяч\w*|тыс\.?)\s+на\s+(\d{1,3})\b", text):
        candidates.append((match.start(), int(match.group(1)) * 1000))

    for match in re.finditer(r"\b(?:бюджет|до|за|на|на сумму|в пределах)?\s*(\d{1,3})\s*(?:тысяч\w*|тыс\.?)\b", text):
        candidates.append((match.start(1), int(match.group(1)) * 1000))

    for match in re.finditer(r"\b(\d{1,3})\s*[кk]\b", text):
        candidates.append((match.start(1), int(match.group(1)) * 1000))

    word_numbers = {
        "одна": 1,
        "один": 1,
        "две": 2,
        "два": 2,
        "три": 3,
        "четыре": 4,
        "пять": 5,
        "шесть": 6,
        "семь": 7,
        "восемь": 8,
        "девять": 9,
        "десять": 10,
        "одиннадцать": 11,
        "двенадцать": 12,
        "тринадцать": 13,
        "четырнадцать": 14,
        "пятнадцать": 15,
        "шестнадцать": 16,
        "семнадцать": 17,
        "восемнадцать": 18,
        "девятнадцать": 19,
        "двадцать": 20,
    }
    for match in re.finditer(r"\b(" + "|".join(word_numbers) + r")\s+(?:тысяч\w*|тыс\.?)\b", text):
        candidates.append((match.start(1), word_numbers[match.group(1)] * 1000))

    for match in re.finditer(r"\b(?:бюджет|до|за|на сумму|в пределах)\s*(\d{1,3})[ .](\d{3})\b", text):
        candidates.append((match.start(1), int(match.group(1) + match.group(2))))

    for match in re.finditer(r"\b(?:бюджет|до|за|на сумму|в пределах|лучше)\s*([1-9]\d{3,5})\b", text):
        candidates.append((match.start(1), int(match.group(1))))

    if _budget_was_requested(context_text or "") or _bare_budget_context(text):
        for match in re.finditer(r"(?<!\d)([1-9]\d{3,5})(?!\d)", text):
            if not _looks_like_non_budget_number(text, match.start(), match.end()):
                candidates.append((match.start(1), int(match.group(1))))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _budget_was_requested(context_text: str) -> bool:
    normalized = context_text.lower().replace("ё", "е")
    return bool(re.search(r"\b(?:бюджет|сумм\w*|сколько\s+готов\w*\s+потратить|на\s+какой\s+бюджет|ориентируемся)\b", normalized))


def _bare_budget_context(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:букет\w*|цвет\w*|пион\w*|роз\w*|тюльпан\w*|нежн\w*|ярк\w*|самовывоз\w*|доставк\w*)\b",
            text,
        )
    )


def _looks_like_non_budget_number(text: str, start: int, end: int) -> bool:
    if _looks_like_year_in_date(text, start, end):
        return True
    before = text[max(0, start - 24):start]
    return bool(re.search(r"\b(?:дом|д\.|кв\.?|квартира|номер|заказ)\s*$", before))


def _looks_like_year_in_date(text: str, start: int, end: int) -> bool:
    year = int(text[start:end])
    if year < 1900 or year > 2100:
        return False
    before = text[max(0, start - 20):start]
    if re.search(r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+$", before):
        return True
    return bool(re.search(r"\b(?:[1-9]|[12]\d|3[01])[.]\s*(?:0?[1-9]|1[0-2])[.]\s*$", before))


def _extract_colors(text: str) -> list[str]:
    color_patterns = (
        ("синий", r"\bсин\w*"),
        ("белый", r"\bбел\w*"),
        ("голубой", r"\bголуб\w*"),
        ("красный", r"\bкрасн\w*"),
        ("розовый", r"\bрозов\w*"),
        ("желтый", r"\bжелт\w*"),
        ("фиолетовый", r"\bфиолет\w*"),
        ("кремовый", r"\bкрем\w*"),
    )
    preferences = [color for color, pattern in color_patterns if re.search(pattern, text)]
    if re.search(r"\bнежн\w*", text):
        preferences.append("нежный стиль")
    if re.search(r"\bярк\w*", text):
        preferences.append("яркий стиль")
    if re.search(r"\bкорзин\w*", text):
        preferences.append("корзина")
    product_patterns = (
        ("розы", r"\bроз(?:ы|а|у|ами|ах)?\b"),
        ("пионы", r"\bпион\w*\b"),
        ("тюльпаны", r"\bтюльпан\w*\b"),
        ("хризантемы", r"\bхризантем\w*\b"),
        ("гортензии", r"\bгортензи\w*\b"),
    )
    for label, pattern in product_patterns:
        if re.search(pattern, text) and label not in preferences:
            preferences.append(label)
    return preferences


def _extract_forbidden_flowers(text: str) -> list[str]:
    forbidden = []
    if re.search(r"(без|не надо|никаких)\s+хризант", text):
        forbidden.append("хризантемы")
    return forbidden


def _extract_fulfillment_type(text: str) -> str | None:
    pickup_matches = [
        match for match in re.finditer(r"\bсамовывоз\w*\b|\bсам\s+забер\w*\b|\bзабер\w*\s+сам\b", text)
        if not _is_negated_match(text, match.start())
    ]
    delivery_matches = [
        match for match in re.finditer(r"\bдоставк\w*\b|адрес доставки|\bпривез\w*\b", text)
        if not _is_negated_match(text, match.start())
    ]
    last_pickup = pickup_matches[-1].start() if pickup_matches else -1
    last_delivery = delivery_matches[-1].start() if delivery_matches else -1
    if last_pickup < 0 and last_delivery < 0:
        return None
    return "delivery" if last_delivery > last_pickup else "pickup"


def _is_negated_match(text: str, start: int) -> bool:
    before = text[max(0, start - 24):start]
    return bool(re.search(r"(?:\bне\s+(?:надо\s+|нужн\w*\s+)?|\bбез\s+)$", before))


_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def _extract_delivery_date(text: str, *, today: date) -> str | None:
    today_index = text.rfind("сегодня")
    tomorrow_index = text.rfind("завтра")
    if today_index > tomorrow_index:
        return today.isoformat()
    if tomorrow_index > today_index:
        return (today + timedelta(days=1)).isoformat()
    month_match = re.search(
        r"\b([1-9]|[12]\d|3[01])\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+(20\d{2}))?\b",
        text,
    )
    if month_match:
        day = int(month_match.group(1))
        month = _MONTHS[month_match.group(2)]
        explicit_year = month_match.group(3)
        year = int(explicit_year or today.year)
        candidate = date(year, month, day)
        if explicit_year is None and candidate < today:
            candidate = date(today.year + 1, month, day)
        return candidate.isoformat()
    return None


def _extract_delivery_time(text: str) -> str | None:
    match = re.search(r"\b([01]?\d|2[0-3])[:.](\d{2})\b", text)
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _extract_address(text: str) -> str | None:
    fallback: str | None = None
    street_marker = r"(?:ул\.?|улиц\w*|проспект|пер\.?|переулок)"
    address_tail = r"\s+[А-Яа-яЁёA-Za-z.\- ]*\d+[А-Яа-яA-Za-z0-9/\-]*(?:\s*(?:кв|квартира|офис|подъезд|корпус|к|стр)\.?\s*\d+[А-Яа-яA-Za-z0-9/\-]*)*"
    for line in text.splitlines():
        line_for_address = re.split(r"(?:\+7|8)\d{10}", line, maxsplit=1)[0]
        lowered = line.lower().replace("ё", "е")
        if re.search(r"\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b", lowered):
            continue
        # High-confidence degraded mode: explicit delivery verb with "на <street/word> <number>".
        delivery_match = re.search(
            rf"\b(?:достав\w*|привез\w*)\s+на\s+(({street_marker}\s+)?[А-Яа-яЁёA-Za-z.\-]+{address_tail})",
            line_for_address,
            re.IGNORECASE,
        )
        if delivery_match:
            fallback = _normalize_address_candidate(delivery_match.group(1))
            continue
        # Or an explicit street marker + number.
        marker_match = re.search(rf"\b({street_marker}{address_tail})", line_for_address, re.IGNORECASE)
        if marker_match:
            fallback = _normalize_address_candidate(marker_match.group(1))
    return fallback


def _normalize_address_candidate(candidate: str) -> str:
    candidate = candidate.strip(" ,.")
    candidate = re.sub(r"^улиц[уе]\b", "улица", candidate, flags=re.IGNORECASE)
    return candidate


def _phones(text: str) -> list[str]:
    return re.findall(r"(?:\+7|8)\d{10}", text)


def _extract_contacts_by_dialog_context(messages: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    pending_role: str | None = None
    for message in messages:
        stripped = _strip_role(message)
        lowered = stripped.lower().replace("ё", "е")
        if message.lower().startswith(("менеджер:", "алина:")):
            if "отправител" in lowered or re.search(r"\bвас\b.*\b(номер|телефон)", lowered):
                pending_role = "sender"
            elif "получател" in lowered:
                pending_role = "recipient"
            continue
        if not _is_client_message(message) or pending_role is None:
            continue
        match = re.search(r"([А-ЯЁ][а-яё]+)\s+((?:\+7|8)\d{10})", stripped)
        if not match:
            continue
        result[f"{pending_role}_name"] = match.group(1)
        result[f"{pending_role}_phone"] = match.group(2)
        pending_role = None
    return result


def _extract_sender_phone(text: str, *, exclude_phone: str | None = None) -> str | None:
    phones = _phones(text)
    if exclude_phone:
        phones = [phone for phone in phones if phone != exclude_phone]
    return phones[0] if phones else None


def _extract_recipient_phone(text: str) -> str | None:
    phones = _phones(text)
    return phones[1] if len(phones) > 1 else None


def _extract_sender_name(text: str, *, exclude_phone: str | None = None) -> str | None:
    for match in re.finditer(r"(?:^|,|\s)([А-ЯЁ][а-яё]+)\s+((?:\+7|8)\d{10})", text):
        if exclude_phone and match.group(2) == exclude_phone:
            continue
        return match.group(1)
    return None


def _extract_recipient_name(text: str) -> str | None:
    match = re.search(r"получатель\s+([А-ЯЁ][а-яё]+)", text, re.IGNORECASE)
    if match:
        return match.group(1)
    pairs = re.findall(r"(?:^|,|\s)([А-ЯЁ][а-яё]+)\s+(?:\+7|8)\d{10}", text)
    return pairs[1] if len(pairs) > 1 else None


def _extract_payment_method(text: str) -> str | None:
    if any(word in text for word in ("перевод", "карт", "сбер", "тиньк", "сбп")):
        return "transfer"
    if "налич" in text or "на месте" in text or "при получении" in text:
        return "cash"
    if "usdt" in text or "btc" in text or "крипт" in text:
        return "crypto"
    return None


def _extract_postcard_text(text: str) -> str | None:
    if re.search(r"открытк\w*\s+(не\s+нуж|не надо|без)", text) or re.search(r"без\s+открытк", text):
        return "not_needed"
    match = re.search(r"открытк\w*[:\-—]?\s*['\"]?([^\n'\"]{3,80})", text)
    return match.group(1).strip() if match else None


def _extract_anonymous(text: str) -> bool | None:
    if "аноним" in text:
        if any(word in text for word in ("не аноним", "неаноним", "можно сказать от кого")):
            return False
        return True
    return None


def _extract_photo_report_requested(text: str) -> bool | None:
    if "фотоотчет" in text or "фото отч" in text or "фото готов" in text:
        return True
    return None
