from __future__ import annotations

from dataclasses import dataclass
import re

from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.order_card import _business_field_value
from amelia_manager.order_state import OrderState


FLORIST_NEXT_STEP_CODES = (
    "ask_budget",
    "ask_bouquet_preferences",
    "ask_when_where",
    "ask_fulfillment_type",
    "ask_date",
    "ask_pickup_time",
    "ask_delivery_time",
    "ask_pickup_time_within_shop_hours",
    "ask_delivery_address",
    "ask_upsell",
    "ask_contacts",
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
    missing: tuple[str, ...] = ()
    fulfillment_type: str | None = None


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
            "Уточни пожелания к букету одним вопросом: оттенки, стиль или любимые цветы. Не задавай второй вопрос и не спрашивай доставку или самовывоз на этом шаге.",
        )
    when_where_missing = _missing_when_where_fields(state)
    if when_where_missing:
        profile = company_profile or load_company_profile("amelia_flowers")
        return NextStep(
            "ask_when_where",
            _when_where_instruction(when_where_missing, state, profile),
            missing=when_where_missing,
            fulfillment_type=state.fulfillment_type,
        )
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
    if _should_offer_upsell(state, company_profile):
        profile = company_profile or load_company_profile("amelia_flowers")
        offers = format_upsell_offers(profile)
        return NextStep(
            "ask_upsell",
            f"Один раз до сбора контактов мягко предложи допродажу: {offers}. Задай один вопрос, нужно ли что-то добавить. Если клиент откажется или повод чувствительный — больше не предлагай.",
        )
    contacts_missing = _missing_contact_fields(state)
    if contacts_missing:
        return NextStep(
            "ask_contacts",
            _contacts_instruction(contacts_missing, state),
            missing=contacts_missing,
            fulfillment_type=state.fulfillment_type,
        )
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


def _should_offer_upsell(state: OrderState, company_profile: CompanyProfile | None) -> bool:
    profile = company_profile or load_company_profile("amelia_flowers")
    if not profile.upsell_offers:
        return False
    if state.custom_fields.get("occasion_sensitive") is True:
        return False
    if state.custom_fields.get("upsell_offered") is True or state.custom_fields.get("upsell_declined") is True:
        return False
    if state.sender_name or state.sender_phone:
        return False
    if not (state.budget and state.colors and state.fulfillment_type and state.delivery_date and state.delivery_time):
        return False
    if state.fulfillment_type == "delivery" and not state.address:
        return False
    return True


def _missing_when_where_fields(state: OrderState) -> tuple[str, ...]:
    missing: list[str] = []
    if not state.fulfillment_type:
        missing.append("fulfillment_type")
    if not state.delivery_date:
        missing.append("delivery_date")
    if not state.delivery_time:
        missing.append("delivery_time")
    if state.fulfillment_type != "pickup" and not state.address:
        missing.append("address")
    if _group_repeated_without_progress(state, "ask_when_where", missing):
        return (missing[0],)
    if len(missing) == 4 and _group_was_asked(state, "ask_when_where"):
        return ("fulfillment_type",)
    return tuple(missing)


def _missing_contact_fields(state: OrderState) -> tuple[str, ...]:
    missing = [field for field in ("sender_name", "sender_phone") if not getattr(state, field)]
    if state.fulfillment_type == "delivery":
        missing.extend(field for field in ("recipient_name", "recipient_phone") if not getattr(state, field))
    if _group_repeated_without_progress(state, "ask_contacts", missing):
        return (missing[0],)
    if len(missing) >= 4 and _group_was_asked(state, "ask_contacts"):
        return ("sender_name",)
    return tuple(missing)


def _group_was_asked(state: OrderState, group_code: str) -> bool:
    asked = state.custom_fields.get("_asked_groups")
    return isinstance(asked, dict) and bool(asked.get(group_code))


def _group_repeated_without_progress(state: OrderState, group_code: str, missing: list[str]) -> bool:
    asked = state.custom_fields.get("_asked_groups")
    if not isinstance(asked, dict):
        return False
    previous = asked.get(group_code)
    if previous is True:
        return False
    if not isinstance(previous, (list, tuple)):
        return False
    return tuple(previous) == tuple(missing)


def _when_where_instruction(missing: tuple[str, ...], state: OrderState, profile: CompanyProfile) -> str:
    repeated = _group_was_asked(state, "ask_when_where") and len(missing) == 1
    if missing == ("fulfillment_type",):
        return "Уточни прямо одним вопросом: доставка или самовывоз."
    if set(missing) == {"fulfillment_type", "address"}:
        return "Уточни только формат заказа: доставка с адресом, куда везти, или самовывоз."
    if set(missing) == {"fulfillment_type", "delivery_date", "delivery_time", "address"}:
        return "Уточни одним вопросом, когда нужен букет и куда его везти; если клиент заберёт сам, адрес не нужен."
    parts: list[str] = []
    if "delivery_date" in missing:
        parts.append("число")
    if "delivery_time" in missing:
        parts.append("время")
    if "address" in missing:
        parts.append("адрес доставки")
    if "fulfillment_type" in missing:
        parts.append("доставка или самовывоз")
    joined = " и ".join(parts)
    if state.fulfillment_type == "pickup":
        pickup_address = profile.pickup_address or "адрес самовывоза"
        if missing == ("delivery_time",) and repeated:
            return f"Спроси прямо, другими словами: к какому времени клиент заберёт букет самовывозом с {pickup_address}?"
        if missing == ("delivery_time",):
            return f"Уточни только время для самовывоза с {pickup_address}."
        if repeated:
            return f"Спроси прямо, другими словами: {joined} для самовывоза."
        return f"Уточни только {joined} для самовывоза."
    if repeated:
        return f"Спроси прямо, другими словами: {joined}."
    return f"Уточни только {joined}. Не повторяй уже заполненные поля группы."


def _contacts_instruction(missing: tuple[str, ...], state: OrderState) -> str:
    need_sender = any(field.startswith("sender_") for field in missing)
    need_recipient = any(field.startswith("recipient_") for field in missing)
    repeated = _group_was_asked(state, "ask_contacts") and len(missing) == 1
    if need_sender and need_recipient:
        if _group_was_asked(state, "ask_contacts"):
            first_field = missing[0]
            if first_field == "sender_name":
                return "Спроси прямо, другими словами: ваше имя для связи по заказу."
            if first_field == "sender_phone":
                return "Спроси прямо, другими словами: ваш телефон для связи по заказу."
            if first_field == "recipient_name":
                return "Спроси прямо, другими словами: имя получателя."
            if first_field == "recipient_phone":
                return "Спроси прямо, другими словами: телефон получателя."
        return "Попроси имя и телефон отправителя, и имя с телефоном получателя."
    if need_sender:
        if repeated:
            if missing == ("sender_name",):
                return "Спроси прямо, другими словами: ваше имя для связи по заказу."
            if missing == ("sender_phone",):
                return "Спроси прямо, другими словами: ваш телефон для связи по заказу."
        return "Попроси только недостающие имя или телефон отправителя для связи по заказу."
    if need_recipient:
        if repeated:
            if missing == ("recipient_name",):
                return "Спроси прямо, другими словами: имя получателя."
            if missing == ("recipient_phone",):
                return "Спроси прямо, другими словами: телефон получателя."
        return "Попроси только недостающие имя или телефон получателя."
    return "Попроси недостающие контакты по заказу."


def format_upsell_offers(profile: CompanyProfile) -> str:
    parts: list[str] = []
    for offer in profile.upsell_offers:
        if offer.price is None:
            parts.append(offer.name)
        else:
            parts.append(f"{offer.name} {offer.price} ₽")
    return ", ".join(parts)


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
