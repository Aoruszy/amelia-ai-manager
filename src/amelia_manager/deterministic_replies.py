from __future__ import annotations

import re

from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.order_card import OrderCard
from amelia_manager.order_policy import NextStep, format_upsell_offers


def deterministic_order_reply(
    next_step: NextStep,
    card: OrderCard | None,
    *,
    recent_messages: list[str] | None = None,
    stock_context: str | None = None,
    company_profile: CompanyProfile | None = None,
) -> str | None:
    profile = company_profile or load_company_profile("amelia_flowers")
    if card and card.is_ready_for_admin_request():
        return format_client_order_summary(card, company_profile=profile)

    stock_reply = _stock_fallback(recent_messages or [], stock_context or "")
    if stock_reply:
        return stock_reply

    pickup_address = profile.pickup_address or "адреса самовывоза"
    replies = {
        "ask_budget": "Подскажите, на какой бюджет ориентируемся? 🌸",
        "ask_bouquet_preferences": "Поняла. Какие оттенки, стиль или цветы больше нравятся?",
        "ask_fulfillment_type": "Хорошо, по букету поняла. Это будет доставка или самовывоз?",
        "ask_date": "На какое число нужен букет?",
        "ask_pickup_time": f"К какому времени удобно забрать букет самовывозом с {pickup_address}?",
        "ask_pickup_time_within_shop_hours": "Самовывоз возможен в часы работы магазина 09:00–20:00. Выберите, пожалуйста, другое время в этом интервале.",
        "ask_delivery_time": "К какому времени или в какой интервал доставить букет?",
        "ask_delivery_address": "Подскажите адрес доставки, пожалуйста.",
        "ask_upsell": f"Можно добавить к заказу: {format_upsell_offers(profile)}. Нужно что-то из этого?",
        "ask_sender_contacts": "Подскажите ваше имя и номер телефона для связи по заказу.",
        "ask_recipient_contacts": "Подскажите имя и номер телефона получателя.",
        "ask_payment_or_confirm_pickup": "Данные по самовывозу записала. Как удобнее оплатить: переводом/картой или на месте?",
        "ask_anonymous_or_payment": "Подскажите, доставка будет анонимной или можно сказать от кого букет? И какой способ оплаты удобен?",
    }
    return replies.get(next_step.code)


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
