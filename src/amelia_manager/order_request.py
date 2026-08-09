from __future__ import annotations

from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.order_card import OrderCard


def format_admin_order_request(
    *,
    order_id: int,
    client_label: str,
    card: OrderCard,
    company_profile: CompanyProfile | None = None,
    case_type: str | None = None,
) -> str:
    profile = company_profile or load_company_profile("amelia_flowers")
    if profile.business_type != "florist":
        return _format_generic_admin_request(
            order_id=order_id,
            client_label=client_label,
            card=card,
            profile=profile,
            case_type=case_type,
        )
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


def _format_generic_admin_request(
    *,
    order_id: int,
    client_label: str,
    card: OrderCard,
    profile: CompanyProfile,
    case_type: str | None,
) -> str:
    lines = [
        f"📩 Новая заявка {profile.company_name}",
        f"ID: {order_id}",
        f"Клиент Telegram: {client_label}",
    ]
    if case_type:
        lines.append(f"Тип: {case_type}")
    if card.delivery_date or card.delivery_time:
        lines.append(f"Дата/время: {_fmt_date(card.delivery_date)} {card.delivery_time or ''}".strip())
    if card.sender_name or card.sender_phone:
        lines.append(f"Клиент: {card.sender_name or 'не указан'}, {card.sender_phone or 'телефон не указан'}")
    if card.address:
        lines.append(f"Адрес: {card.address}")
    if card.budget:
        lines.append(f"Бюджет: {card.budget} ₽")
    for key, value in card.custom_fields.items():
        if value not in (None, "", [], {}):
            lines.append(f"{key}: {value}")
    lines.append("Статус: нужно подтвердить детали")
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
