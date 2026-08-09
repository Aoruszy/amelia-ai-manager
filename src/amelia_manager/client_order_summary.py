from __future__ import annotations

from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.order_card import OrderCard


def format_client_order_summary(card: OrderCard, *, company_profile: CompanyProfile | None = None) -> str:
    profile = company_profile or load_company_profile("amelia_flowers")
    product_label = "Букет" if profile.business_type == "florist" else "Заказ"
    if card.fulfillment_type == "pickup":
        pickup_address = profile.pickup_address or "адрес самовывоза не указан"
        lines = [
            "Итог заказа:",
            f"• Формат: Самовывоз с {pickup_address}",
            f"• Время: {_fmt_date(card.delivery_date)} {card.delivery_time or ''}".strip(),
            f"• Бюджет: {card.budget} ₽" if card.budget else "• Бюджет: не указан",
            f"• {product_label}: {_fmt_list(card.colors)}",
            f"• Имя: {card.sender_name or 'не указано'}",
            f"• Телефон: {card.sender_phone or 'не указан'}",
        ]
        if card.payment_method:
            lines.append(f"• Оплата: {_fmt_payment(card.payment_method)}")
        lines.append("Передаю заказ менеджеру: он подтвердит детали и подскажет по оплате 🌸")
        return "\n".join(lines)
    lines = [
        "Итог заказа:",
        "• Формат: Доставка",
        f"• Время: {_fmt_date(card.delivery_date)} {card.delivery_time or ''}".strip(),
        f"• Адрес: {card.address or 'не указан'}",
        f"• Бюджет: {card.budget} ₽" if card.budget else "• Бюджет: не указан",
        f"• {product_label}: {_fmt_list(card.colors)}",
        f"• Получатель: {card.recipient_name or 'не указан'}, {card.recipient_phone or 'телефон не указан'}",
        f"• Отправитель: {card.sender_name or 'не указан'}, {card.sender_phone or 'телефон не указан'}",
        f"• Оплата: {_fmt_payment(card.payment_method)}",
        "Передаю заказ менеджеру: он подтвердит детали и пришлёт реквизиты/ссылку для оплаты 🌸",
    ]
    return "\n".join(lines)


def _fmt_date(value: str | None) -> str:
    return {"today": "сегодня", "tomorrow": "завтра"}.get(value or "", value or "не указано")


def _fmt_payment(value: str | None) -> str:
    return {"transfer": "переводом/картой", "cash": "на месте", "crypto": "криптовалютой"}.get(value or "", value or "не указана")


def _fmt_list(values: list[str]) -> str:
    return ", ".join(values) if values else "пожелания не указаны"
