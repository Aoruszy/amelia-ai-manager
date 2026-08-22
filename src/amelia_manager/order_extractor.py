from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.order_card import OrderCard, invalid_order_state_field_codes, merge_order_state
from amelia_manager.order_state import OrderState, extract_order_state
from amelia_manager.structured_generation import generate_with_optional_schema


class LLM(Protocol):
    async def generate(self, prompt: str, **kwargs) -> str: ...


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


@dataclass(frozen=True)
class ExtractionResult:
    state: OrderState
    ignored_field_codes: list[str]


async def extract_order_state_with_llm(
    llm: LLM,
    recent_messages: list[str],
    *,
    company_profile: CompanyProfile | None = None,
    today=None,
    timezone_name: str = "Europe/Kaliningrad",
    catalog_options: list[dict[str, object]] | None = None,
) -> OrderState:
    return (
        await extract_order_state_with_llm_result(
            llm,
            recent_messages,
            company_profile=company_profile,
            today=today,
            timezone_name=timezone_name,
            catalog_options=catalog_options,
        )
    ).state


async def extract_order_state_with_llm_result(
    llm: LLM,
    recent_messages: list[str],
    *,
    company_profile: CompanyProfile | None = None,
    today=None,
    timezone_name: str = "Europe/Kaliningrad",
    catalog_options: list[dict[str, object]] | None = None,
) -> ExtractionResult:
    regex_state = extract_order_state(recent_messages, today=today, timezone_name=timezone_name, catalog_options=catalog_options)
    try:
        raw = await generate_with_optional_schema(
            llm,
            _build_extraction_prompt(recent_messages, company_profile=company_profile),
            response_schema=ExtractedOrderState.model_json_schema(),
        )
        llm_state = ExtractedOrderState.model_validate(_parse_json_object(raw)).to_state()
        ignored_field_codes = invalid_order_state_field_codes(llm_state) if (company_profile is None or company_profile.business_type == "florist") else []
        if llm_state.address and not looks_like_address(llm_state.address):
            llm_state = OrderState(**{**llm_state.__dict__, "address": None})
    except Exception:
        return ExtractionResult(regex_state, [])
    return ExtractionResult(_merge_states(regex_state, llm_state), ignored_field_codes)


def looks_like_address(value: str | None) -> bool:
    if not value:
        return False
    text = value.strip()
    if not 5 <= len(text) <= 120:
        return False
    normalized = text.lower().replace("ё", "е")
    if not re.search(r"\d", normalized):
        return False
    if re.search(r"(?:\+7|8)\d{10}", normalized):
        return False
    if re.search(r"\b(?:бюджет|до)\s*\d{3,6}\b|\bтысяч\w*\b|₽|руб", normalized):
        return False
    if re.search(r"\b(?:сегодня|завтра)\b|\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b", normalized):
        return False
    if re.search(r"\b\d{1,2}[:.]\d{2}\b", normalized):
        return False
    has_street_marker = bool(re.search(r"\b(?:ул\.?|улиц\w*|проспект|пер\.?|переулок)\b", normalized))
    has_word_number_pair = bool(re.search(r"\b[а-яa-z.\-]{2,},?\s+\d+[а-яa-z0-9/\-]*\b", normalized))
    return has_street_marker or has_word_number_pair


def _build_extraction_prompt(recent_messages: list[str], *, company_profile: CompanyProfile | None = None) -> str:
    if company_profile is None or company_profile.business_type == "florist":
        field_block = "Поля: occasion, budget, colors, forbidden_flowers, fulfillment_type(delivery/pickup), delivery_date(ISO YYYY-MM-DD), delivery_time(HH:MM), address, sender_name, sender_phone, recipient_name, recipient_phone, payment_method(transfer/cash/crypto), postcard_text, anonymous, photo_report_requested, custom_fields. Если клиент назвал диапазон бюджета, budget ставь по верхней границе, а исходную вилку сохрани в custom_fields.budget_range."
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
    data.pop("sheet_row_written", None)
    return OrderState(**data)
