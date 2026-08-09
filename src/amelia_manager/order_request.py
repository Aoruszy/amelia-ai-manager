from __future__ import annotations

from amelia_manager.order_card import OrderCard


def format_admin_order_request(*, order_id: int, client_label: str, card: OrderCard) -> str:
    fulfillment = "самовывоз" if card.fulfillment_type == "pickup" else "доставка"
    lines = [
        "🌸 Новая заявка Amelia Flowers",
        f"ID: {order_id}",
        f"Клиент Telegram: {client_label}",
        f"Тип: {fulfillment}",
        f"Дата/время: {_fmt_date(card.delivery_date)} {card.delivery_time or ''}".strip(),
        f"Бюджет: {card.budget} ₽" if card.budget else "Бюджет: не указан",
        f"Пожелания: {', '.join(card.colors) if card.colors else 'не указаны'}",
    ]
    if card.forbidden_flowers:
        lines.append(f"Исключить: {', '.join(card.forbidden_flowers)}")
    if card.fulfillment_type == "delivery":
        lines.extend(
            [
                f"Адрес: {card.address or 'не указан'}",
                f"Получатель: {card.recipient_name or 'не указан'}, {card.recipient_phone or 'телефон не указан'}",
                f"Анонимно: {_fmt_bool(card.anonymous)}",
            ]
        )
    else:
        lines.append("Самовывоз: Сергеева, 61")
    lines.extend(
        [
            f"Клиент: {card.sender_name or 'не указан'}, {card.sender_phone or 'телефон не указан'}",
            f"Открытка: {_fmt_postcard(card.postcard_text)}",
            f"Фотоотчёт: {_fmt_bool(card.photo_report_requested)}",
            f"Оплата: {_fmt_payment(card.payment_method)}",
            "Статус: нужно подтвердить сборку/оплату",
        ]
    )
    return "\n".join(lines)


def _fmt_date(value: str | None) -> str:
    return {"today": "сегодня", "tomorrow": "завтра"}.get(value or "", value or "не указано")


def _fmt_bool(value: bool | None) -> str:
    if value is True:
        return "да"
    if value is False:
        return "нет"
    return "не указано"


def _fmt_postcard(value: str | None) -> str:
    if value == "not_needed":
        return "не нужна"
    return value or "не указана"


def _fmt_payment(value: str | None) -> str:
    return {"transfer": "переводом/картой", "cash": "наличными", "crypto": "криптовалютой"}.get(value or "", value or "не указана")
