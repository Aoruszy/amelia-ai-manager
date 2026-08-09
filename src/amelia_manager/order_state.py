from __future__ import annotations

import re
from dataclasses import dataclass, field


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


def extract_order_state(messages: list[str]) -> OrderState:
    client_messages = [_strip_role(message) for message in messages if _is_client_message(message)]
    text = "\n".join(client_messages).lower().replace("ё", "е")
    context_text = "\n".join(_strip_role(message) for message in messages).lower().replace("ё", "е")
    original = "\n".join(client_messages)
    contacts = _extract_contacts_by_dialog_context(messages)
    recipient_name = contacts.get("recipient_name") or _extract_recipient_name(original)
    recipient_phone = contacts.get("recipient_phone") or _extract_recipient_phone(original)
    sender_name = contacts.get("sender_name") or _extract_sender_name(original, exclude_phone=recipient_phone)
    sender_phone = contacts.get("sender_phone") or _extract_sender_phone(original, exclude_phone=recipient_phone)

    return OrderState(
        occasion=_extract_occasion(text),
        budget=_extract_budget(text),
        colors=_extract_colors(text),
        forbidden_flowers=_extract_forbidden_flowers(text),
        fulfillment_type=_extract_fulfillment_type(text),
        delivery_date=_extract_delivery_date(context_text),
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


def _extract_budget(text: str) -> int | None:
    patterns = [r"бюджет\s*(\d[\d\s]*)", r"до\s*(\d[\d\s]*)"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(re.sub(r"\D", "", match.group(1)))
    standalone_amounts = [int(value) for value in re.findall(r"(?<!\d)([1-9]\d{3,5})(?!\d)", text)]
    return standalone_amounts[-1] if standalone_amounts else None
    return None


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
    return preferences


def _extract_forbidden_flowers(text: str) -> list[str]:
    forbidden = []
    if re.search(r"(без|не надо|никаких)\s+хризант", text):
        forbidden.append("хризантемы")
    return forbidden


def _extract_fulfillment_type(text: str) -> str | None:
    pickup_matches = list(re.finditer(r"\bсамовывоз\w*\b", text))
    delivery_matches = list(re.finditer(r"\bдоставк\w*\b|адрес доставки", text))
    last_pickup = pickup_matches[-1].start() if pickup_matches else -1
    last_delivery = delivery_matches[-1].start() if delivery_matches else -1
    if last_pickup < 0 and last_delivery < 0:
        return None
    return "delivery" if last_delivery > last_pickup else "pickup"


def _extract_delivery_date(text: str) -> str | None:
    today_index = text.rfind("сегодня")
    tomorrow_index = text.rfind("завтра")
    if today_index > tomorrow_index:
        return "today"
    if tomorrow_index > today_index:
        return "tomorrow"
    month_match = re.search(
        r"\b([1-9]|[12]\d|3[01])\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b",
        text,
    )
    if month_match:
        return f"{int(month_match.group(1))} {month_match.group(2)}"
    return None


def _extract_delivery_time(text: str) -> str | None:
    match = re.search(r"\b([01]?\d|2[0-3])[:.](\d{2})\b", text)
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _extract_address(text: str) -> str | None:
    seen_delivery_context = False
    fallback: str | None = None
    for line in text.splitlines():
        lowered = line.lower().replace("ё", "е")
        if "достав" in lowered:
            seen_delivery_context = True

        if "достав" in lowered and _phones(line):
            before_phone = re.split(r"(?:\+7|8)\d{10}", line, maxsplit=1)[0]
            match = re.search(r"достав\w*,?\s*([А-Яа-яЁёA-Za-z.\- ]+\s+\d+[А-Яа-яA-Za-z0-9/\-]*)", before_phone, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip(" ,.")
                candidate_low = candidate.lower().replace("ё", "е")
                if not any(word in candidate_low for word in ("бюджет", "сегодня", "завтра", "доставка")):
                    fallback = candidate
            continue

        if _phones(line) or any(marker in lowered for marker in ("получатель", "отправитель")):
            continue
        if re.search(r"\b(?:бюджет|до)\s*\d{3,6}\b", lowered):
            continue
        if re.fullmatch(r"\s*(к\s*)?\d{1,2}[:.]\d{2}\s*(можно)?\??\s*", lowered):
            continue
        if re.search(r"\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b", lowered):
            continue

        # Lines like "Доставка завтра 11:00" describe fulfillment/time, not address.
        if "достав" in lowered and re.search(r"\b(сегодня|завтра)\b", lowered) and re.search(r"\b\d{1,2}[:.]?\d{0,2}\b", lowered):
            continue

        has_street_prefix = bool(re.search(r"\b(ул\.?|улица|проспект|пер\.?|переулок)\b", lowered))
        address_pattern = r"[А-Яа-яЁёA-Za-z.\- ]+\s+\d+[А-Яа-яA-Za-z0-9/\-]*(?:\s*(?:кв|квартира|офис|подъезд|корпус|к|стр)\.?\s*\d+[А-Яа-яA-Za-z0-9/\-]*)*"
        may_be_bare_address = seen_delivery_context and bool(re.search(address_pattern, line, re.IGNORECASE))
        if not ("достав" in lowered or has_street_prefix or may_be_bare_address):
            continue

        match = re.search(r"(?:.*?достав\w*\s+(?:на\s+)?)?(" + address_pattern + r")", line, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(" ,.")
            candidate_low = candidate.lower().replace("ё", "е")
            if not any(word in candidate_low for word in ("бюджет", "сегодня", "завтра", "доставка")):
                fallback = candidate
    return fallback


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
