from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.order_card import OrderCard, merge_order_state
from amelia_manager.order_state import OrderState, extract_order_state


class LLM(Protocol):
    async def generate(self, prompt: str) -> str: ...


class ExtractedOrderState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    occasion: str | None = None
    budget: int | None = Field(default=None, ge=0)
    colors: list[str] = Field(default_factory=list)
    forbidden_flowers: list[str] = Field(default_factory=list)
    fulfillment_type: str | None = None
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
    custom_fields: dict[str, object] = Field(default_factory=dict)

    def to_state(self) -> OrderState:
        return OrderState(**self.model_dump())


async def extract_order_state_with_llm(
    llm: LLM,
    recent_messages: list[str],
    *,
    company_profile: CompanyProfile | None = None,
    today=None,
    timezone_name: str = "Europe/Kaliningrad",
) -> OrderState:
    regex_state = extract_order_state(recent_messages, today=today, timezone_name=timezone_name)
    try:
        raw = await llm.generate(_build_extraction_prompt(recent_messages, company_profile=company_profile))
        llm_state = ExtractedOrderState.model_validate(_parse_json_object(raw)).to_state()
    except Exception:
        return regex_state
    return _merge_states(regex_state, llm_state)


def _build_extraction_prompt(recent_messages: list[str], *, company_profile: CompanyProfile | None = None) -> str:
    if company_profile is None or company_profile.business_type == "florist":
        field_block = "Поля: occasion, budget, colors, forbidden_flowers, fulfillment_type(delivery/pickup), delivery_date(ISO YYYY-MM-DD), delivery_time(HH:MM), address, sender_name, sender_phone, recipient_name, recipient_phone, payment_method(transfer/cash/crypto), postcard_text, anonymous, photo_report_requested, custom_fields."
    else:
        custom_fields: list[str] = []
        for fields in company_profile.required_fields.values():
            custom_fields.extend(field.code for field in fields)
        unique_custom_fields = ", ".join(dict.fromkeys(custom_fields))
        field_block = (
            "Универсальные поля: budget, fulfillment_type, delivery_date, delivery_time, address, "
            "sender_name, sender_phone, recipient_name, recipient_phone, payment_method, anonymous, photo_report_requested.\n"
            f"Поля профиля складывай в custom_fields: {unique_custom_fields}."
        )
    business = (company_profile or load_company_profile("amelia_flowers")).company_name
    return f"""Извлеки данные заявки для {business} из русской переписки.
Верни только JSON без Markdown. Не выдумывай неизвестные поля.
{field_block}

Переписка:
""" + "\n".join(recent_messages[-30:])


def _parse_json_object(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValidationError.from_exception_data("ExtractedOrderState", [])
    return json.loads(match.group(0))


def _merge_states(regex_state: OrderState, llm_state: OrderState) -> OrderState:
    # Reuse OrderCard's merge semantics, then convert back to OrderState.
    protected_regex_fields = {
        "delivery_date": regex_state.delivery_date,
        "delivery_time": regex_state.delivery_time,
        "budget": regex_state.budget,
        "fulfillment_type": regex_state.fulfillment_type,
    }
    merged_card = merge_order_state(OrderCard(), regex_state)
    merged_card = merge_order_state(merged_card, llm_state)
    data = merged_card.to_dict()
    for field, value in protected_regex_fields.items():
        if value not in (None, "", [], {}):
            data[field] = value
    data.pop("admin_request_sent", None)
    data.pop("client_summary_sent", None)
    return OrderState(**data)
