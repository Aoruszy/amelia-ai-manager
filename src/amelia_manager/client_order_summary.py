from __future__ import annotations

from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.date_formatting import format_human_date
from amelia_manager.order_card import OrderCard, format_budget_display


def format_client_order_summary(card: OrderCard, *, company_profile: CompanyProfile | None = None) -> str:
    profile = company_profile or load_company_profile("amelia_flowers")
    if profile.business_type != "florist":
        return _format_generic_client_summary(card, profile=profile)
    product_label = "Букет" if profile.business_type == "florist" else "Заказ"
    budget_display = format_budget_display(card)
    if card.fulfillment_type == "pickup":
        pickup_address = profile.pickup_address or "адрес самовывоза не указан"
        lines = [
            "Итог заказа:",
            f"• Формат: Самовывоз с {pickup_address}",
            f"• Время: {format_human_date(card.delivery_date, timezone_name=profile.timezone_name)} {card.delivery_time or ''}".strip(),
            f"• Бюджет: {budget_display}" if budget_display else "• Бюджет: не указан",
            f"• {product_label}: {_fmt_list(card.colors)}",
            f"• Имя: {card.sender_name or 'не указано'}",
            f"• Телефон: {card.sender_phone or 'не указан'}",
        ]
        if card.payment_method:
            lines.append(f"• Оплата: {_fmt_payment(card.payment_method)}")
        if card.payment_method:
            lines.append("Передаю заказ менеджеру: он подтвердит детали и подскажет по оплате 🌸")
        else:
            lines.append("Передаю заказ менеджеру: он подтвердит детали заказа 🌸")
        return "\n".join(lines)
    lines = [
        "Итог заказа:",
        "• Формат: Доставка",
        f"• Время: {format_human_date(card.delivery_date, timezone_name=profile.timezone_name)} {card.delivery_time or ''}".strip(),
        f"• Адрес: {card.address or 'не указан'}",
        f"• Бюджет: {budget_display}" if budget_display else "• Бюджет: не указан",
        f"• {product_label}: {_fmt_list(card.colors)}",
        f"• Получатель: {card.recipient_name or 'не указан'}, {card.recipient_phone or 'телефон не указан'}",
        f"• Отправитель: {card.sender_name or 'не указан'}, {card.sender_phone or 'телефон не указан'}",
        f"• Оплата: {_fmt_payment(card.payment_method)}",
        "Передаю заказ менеджеру: он подтвердит детали и пришлёт реквизиты/ссылку для оплаты 🌸",
    ]
    return "\n".join(lines)


def _fmt_payment(value: str | None) -> str:
    return {"transfer": "переводом/картой", "cash": "на месте", "crypto": "криптовалютой"}.get(value or "", value or "не указана")


def _fmt_list(values: list[str]) -> str:
    return ", ".join(values) if values else "пожелания не указаны"


def _format_generic_client_summary(card: OrderCard, *, profile: CompanyProfile) -> str:
    lines = ["Итог заявки:"]
    if card.fulfillment_type == "pickup":
        lines.append(f"• Формат: Самовывоз с {profile.pickup_address or 'адрес самовывоза не указан'}")
    elif card.fulfillment_type == "delivery":
        lines.append("• Формат: Доставка")
    if card.delivery_date or card.delivery_time:
        lines.append(f"• Время: {format_human_date(card.delivery_date, timezone_name=profile.timezone_name)} {card.delivery_time or ''}".strip())
    if card.address:
        lines.append(f"• Адрес: {card.address}")
    budget_display = format_budget_display(card)
    if budget_display:
        lines.append(f"• Бюджет: {budget_display}")
    if card.sender_name or card.sender_phone:
        lines.append(f"• Контакт: {card.sender_name or 'не указано'}, {card.sender_phone or 'телефон не указан'}")
    if card.colors:
        lines.append(f"• Заказ: {_fmt_list(card.colors)}")
    for key, value in card.custom_fields.items():
        if value not in (None, "", [], {}):
            lines.append(f"• {key}: {value}")
    lines.append(f"Передаю заявку менеджеру {profile.manager_name}: он подтвердит детали 🌸")
    return "\n".join(lines)
