from __future__ import annotations

from dataclasses import dataclass
import re

from amelia_manager.company_profile import CompanyProfile
from amelia_manager.order_card import _business_field_value
from amelia_manager.order_state import OrderState


@dataclass(frozen=True)
class NextStep:
    code: str
    instruction: str


def get_next_step(
    state: OrderState,
    *,
    company_profile: CompanyProfile | None = None,
    case_type: str | None = None,
) -> NextStep:
    if company_profile is not None and company_profile.business_type != "florist":
        profile_step = _profile_next_step(state, company_profile, case_type=case_type)
        if profile_step:
            return profile_step
        return NextStep(
            "confirm_profile_case",
            "Данные заявки по профилю собраны. Коротко дай итог и скажи, что передаёшь менеджеру для подтверждения.",
        )

    if not state.budget:
        return NextStep("ask_budget", "Уточни бюджет одним коротким вопросом.")
    if not state.colors:
        return NextStep(
            "ask_bouquet_preferences",
            "Уточни пожелания к букету: оттенки, стиль или любимые цветы. Не спрашивай доставку или самовывоз на этом шаге.",
        )
    if not state.fulfillment_type:
        return NextStep("ask_fulfillment_type", "Уточни, клиенту нужна доставка или самовывоз.")
    if not state.delivery_date:
        return NextStep("ask_date", "Уточни, на какое число нужен букет.")
    if not state.delivery_time:
        if state.fulfillment_type == "pickup":
            return NextStep("ask_pickup_time", "Уточни, к какому времени клиенту удобно забрать букет самовывозом.")
        return NextStep("ask_delivery_time", "Уточни удобное время или интервал доставки.")
    if state.fulfillment_type == "pickup" and not _is_pickup_time_within_shop_hours(state.delivery_time):
        return NextStep(
            "ask_pickup_time_within_shop_hours",
            "Самовывоз возможен в часы работы магазина 09:00–20:00. Попроси выбрать другое время в этом интервале.",
        )
    if state.fulfillment_type == "delivery" and not state.address:
        return NextStep("ask_delivery_address", "Попроси адрес доставки и не передавай диалог человеку.")
    if not state.sender_name or not state.sender_phone:
        return NextStep("ask_sender_contacts", "Попроси имя и телефон отправителя для связи по заказу.")
    if state.fulfillment_type == "delivery" and (not state.recipient_name or not state.recipient_phone):
        return NextStep("ask_recipient_contacts", "Попроси имя и телефон получателя.")
    if state.fulfillment_type == "pickup":
        return NextStep(
            "confirm_pickup_order",
            "Данные по самовывозу собраны. Не спрашивай способ оплаты. Коротко дай итог и скажи, что передаёшь заказ менеджеру для подтверждения.",
        )
    if getattr(state, "payment_method", None):
        return NextStep(
            "confirm_delivery_order",
            "Не подтверждай оплату и заказ самостоятельно. Коротко дай итог и скажи, что передаёшь заказ менеджеру: он подтвердит детали и пришлёт реквизиты/ссылку для оплаты.",
        )
    return NextStep(
        "ask_anonymous_or_payment",
        "Данные по заказу собраны. Уточни, доставка будет анонимной или можно сказать от кого букет, и какой способ оплаты удобен.",
    )


def _profile_next_step(state: OrderState, profile: CompanyProfile, *, case_type: str | None) -> NextStep | None:
    selected_case_type = case_type or _first_case_type(profile)
    if not selected_case_type:
        return None
    for field in profile.required_fields.get(selected_case_type, []):
        if not field.required:
            continue
        if _business_field_value(state, field.code) in (None, "", [], {}):
            return NextStep(f"ask_{field.code}", f"Уточни поле «{field.label}» одним коротким вопросом.")
    return None


def _first_case_type(profile: CompanyProfile) -> str | None:
    return next(iter(profile.required_fields), None)


def _is_pickup_time_within_shop_hours(value: str | None) -> bool:
    if not value:
        return False
    match = re.search(r"\b(\d{1,2})[:.](\d{2})\b", value)
    if not match:
        return True
    hour = int(match.group(1))
    minute = int(match.group(2))
    return (hour, minute) >= (9, 0) and (hour, minute) <= (20, 0)
