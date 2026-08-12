from __future__ import annotations

from dataclasses import dataclass
import re

from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.order_card import _business_field_value
from amelia_manager.order_state import OrderState


FLORIST_NEXT_STEP_CODES = (
    "ask_budget",
    "ask_bouquet_preferences",
    "ask_fulfillment_type",
    "ask_date",
    "ask_pickup_time",
    "ask_delivery_time",
    "ask_pickup_time_within_shop_hours",
    "ask_delivery_address",
    "ask_sender_contacts",
    "ask_recipient_contacts",
    "confirm_pickup_order",
    "confirm_delivery_order",
    "ask_anonymous_or_payment",
)


@dataclass(frozen=True)
class NextStep:
    code: str
    instruction: str


def next_step_codes_for_profile(profile: CompanyProfile) -> list[str]:
    if profile.business_type != "florist":
        codes = [f"ask_{field.code}" for fields in profile.required_fields.values() for field in fields if field.required]
        codes.append("confirm_profile_case")
        return list(dict.fromkeys(codes))
    return list(FLORIST_NEXT_STEP_CODES)


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
            profile = company_profile or load_company_profile("amelia_flowers")
            pickup_address = f" на {profile.pickup_address}" if profile.pickup_address else " самовывозом"
            return NextStep("ask_pickup_time", f"Уточни, к какому времени клиенту удобно забрать букет{pickup_address}.")
        return NextStep("ask_delivery_time", "Уточни удобное время или интервал доставки.")
    if state.fulfillment_type == "pickup" and not _is_pickup_time_within_shop_hours(
        state.delivery_time,
        company_profile=company_profile,
    ):
        profile = company_profile or load_company_profile("amelia_flowers")
        shop_hours = profile.shop_hours or "часы работы магазина"
        return NextStep(
            "ask_pickup_time_within_shop_hours",
            f"Самовывоз возможен в часы работы магазина {shop_hours}. Попроси выбрать другое время в этом интервале.",
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


def _is_pickup_time_within_shop_hours(value: str | None, *, company_profile: CompanyProfile | None = None) -> bool:
    if not value:
        return False
    match = re.search(r"\b(\d{1,2})[:.](\d{2})\b", value)
    if not match:
        return True
    hour = int(match.group(1))
    minute = int(match.group(2))
    start, end = _shop_hour_bounds(company_profile)
    return (hour, minute) >= start and (hour, minute) <= end


def _shop_hour_bounds(company_profile: CompanyProfile | None) -> tuple[tuple[int, int], tuple[int, int]]:
    profile = company_profile or load_company_profile("amelia_flowers")
    hours = profile.shop_hours or ""
    matches = re.findall(r"(\d{1,2})[:.](\d{2})", hours)
    if len(matches) < 2:
        return (9, 0), (20, 0)
    (start_hour, start_minute), (end_hour, end_minute) = matches[:2]
    return (int(start_hour), int(start_minute)), (int(end_hour), int(end_minute))
