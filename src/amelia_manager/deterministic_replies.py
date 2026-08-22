from __future__ import annotations

import re

from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.order_card import OrderCard
from amelia_manager.order_policy import NextStep, format_upsell_offers
from amelia_manager.stock import BudgetOption, BudgetOptions, is_budget_unknown_answer

def deterministic_order_reply(
    next_step: NextStep,
    card: OrderCard | None,
    *,
    recent_messages: list[str] | None = None,
    stock_context: str = "",
    company_profile: CompanyProfile | None = None,
    budget_options: BudgetOptions | list[BudgetOption] | None = None,
) -> str | None:
    profile = company_profile or load_company_profile("amelia_flowers")
    if card and card.is_ready_for_admin_request():
        return format_client_order_summary(card, company_profile=profile)

    stock_reply = _stock_fallback(recent_messages or [], stock_context or "")
    if stock_reply:
        return stock_reply

    budget_options_reply = _budget_options_reply(recent_messages or [], budget_options, profile)
    pickup_address = profile.pickup_address or "адреса самовывоза"
    pickup_hours_reply = _pickup_time_outside_hours_reply(recent_messages or [], profile)
    replies = {
        "ask_budget": budget_options_reply or "Подскажите, на какой бюджет ориентируемся? 🌸",
        "ask_bouquet_preferences": "Поняла. Какие оттенки, стиль или цветы больше нравятся?",
        "ask_when_where": _when_where_reply(next_step, profile),
        "ask_fulfillment_type": "Хорошо, по букету поняла. Это будет доставка или самовывоз?",
        "ask_date": "На какое число нужен букет?",
        "ask_pickup_time": f"К какому времени удобно забрать букет самовывозом с {pickup_address}?",
        "ask_pickup_time_within_shop_hours": pickup_hours_reply,
        "ask_delivery_time": "К какому времени или в какой интервал доставить букет?",
        "ask_delivery_address": "Подскажите адрес доставки, пожалуйста.",
        "ask_upsell": profile.upsell_reply_template.format(offers=format_upsell_offers(profile)),
        "ask_contacts": _contacts_reply(next_step, profile),
        "ask_sender_contacts": "Подскажите ваше имя и номер телефона для связи по заказу.",
        "ask_recipient_contacts": "Подскажите имя и номер телефона получателя.",
        "ask_payment_or_confirm_pickup": "Данные по самовывозу записала. Как удобнее оплатить: переводом/картой или на месте?",
        "ask_anonymous_or_payment": "Подскажите, доставка будет анонимной или можно сказать от кого букет? И какой способ оплаты удобен?",
    }
    return replies.get(next_step.code)


def _when_where_reply(next_step: NextStep, profile: CompanyProfile) -> str:
    missing = set(next_step.missing)
    if missing == {"fulfillment_type", "delivery_date", "delivery_time", "address"}:
        return profile.ask_when_where_full_reply_template
    if missing == {"delivery_time"} and next_step.fulfillment_type == "pickup":
        pickup_address = profile.pickup_address or "адреса самовывоза"
        return f"К какому времени удобно забрать букет самовывозом с {pickup_address}?"
    parts: list[str] = []
    if "fulfillment_type" in missing:
        parts.append("доставка или самовывоз")
    if "delivery_date" in missing:
        parts.append("число")
    if "delivery_time" in missing:
        parts.append("время")
    if "address" in missing:
        parts.append("адрес доставки")
    if not parts:
        return profile.ask_when_where_full_reply_template
    return profile.ask_when_where_parts_reply_template.format(parts=" и ".join(parts))


def _contacts_reply(next_step: NextStep, profile: CompanyProfile) -> str:
    missing = set(next_step.missing)
    if {"sender_name", "sender_phone", "recipient_name", "recipient_phone"}.issubset(missing):
        return profile.ask_contacts_sender_recipient_reply_template
    parts: list[str] = []
    if "sender_name" in missing and "sender_phone" in missing:
        parts.append("ваше имя и телефон")
    elif "sender_name" in missing:
        parts.append("ваше имя")
    elif "sender_phone" in missing:
        parts.append("ваш телефон")
    if "recipient_name" in missing and "recipient_phone" in missing:
        parts.append("имя и телефон получателя")
    elif "recipient_name" in missing:
        parts.append("имя получателя")
    elif "recipient_phone" in missing:
        parts.append("телефон получателя")
    return profile.ask_contacts_parts_reply_template.format(parts=" и ".join(parts or ["контакты по заказу"]))


def _pickup_time_outside_hours_reply(recent_messages: list[str], profile: CompanyProfile) -> str:
    shop_hours = profile.shop_hours or "09:00–20:00"
    latest_time = _latest_time_mention(recent_messages)
    if latest_time:
        return (
            f"Самовывоз к {latest_time} не получится: магазин работает {shop_hours}. "
            "Выберите, пожалуйста, другое время в этом интервале."
        )
    return (
        f"Самовывоз возможен в часы работы магазина {shop_hours}. "
        "Выберите, пожалуйста, другое время в этом интервале."
    )


def _latest_time_mention(recent_messages: list[str]) -> str | None:
    for message in reversed(recent_messages):
        match = re.search(r"\b([01]?\d|2[0-3])[:.](\d{2})\b", message)
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"
    return None


def _stock_fallback(recent_messages: list[str], stock_context: str) -> str | None:
    if not stock_context or "— нет" not in stock_context:
        return None
    last = recent_messages[-1].lower().replace("ё", "е") if recent_messages else ""
    if not any(word in last for word in ("есть", "налич", "пионы", "пион")):
        return None
    for item in re.findall(r"-\s*([^\n—]+)\s*—\s*нет", stock_context.lower().replace("ё", "е")):
        name = item.strip()
        stem = name[:5]
        if stem and stem in last:
            return f"{name} на сегодня нет. Могу подобрать похожий нежный вариант — подскажите, на какой бюджет ориентируемся?"
    return None


def _budget_options_reply(
    recent_messages: list[str],
    budget_options: BudgetOptions | list[BudgetOption] | None,
    profile: CompanyProfile,
) -> str | None:
    latest = recent_messages[-1].lower().replace("ё", "е") if recent_messages else ""
    if not is_budget_unknown_answer(latest):
        return None
    if budget_options is None:
        return None
    hide_names = isinstance(budget_options, BudgetOptions) and budget_options.hide_names
    options = budget_options.items if isinstance(budget_options, BudgetOptions) else budget_options
    if len(options) < 2:
        return None
    if hide_names:
        level_text = ", ".join(f"{option.price} ₽" for option in options)
        return profile.budget_levels_reply_template.format(options=level_text)
    option_text = ", ".join(f"{option.name} — {option.price} ₽" for option in options)
    return profile.budget_options_reply_template.format(options=option_text)
