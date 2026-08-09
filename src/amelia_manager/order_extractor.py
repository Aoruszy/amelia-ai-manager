from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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

    def to_state(self) -> OrderState:
        return OrderState(**self.model_dump())


async def extract_order_state_with_llm(llm: LLM, recent_messages: list[str]) -> OrderState:
    regex_state = extract_order_state(recent_messages)
    try:
        raw = await llm.generate(_build_extraction_prompt(recent_messages))
        llm_state = ExtractedOrderState.model_validate(_parse_json_object(raw)).to_state()
    except Exception:
        return regex_state
    return _merge_states(regex_state, llm_state)


def _build_extraction_prompt(recent_messages: list[str]) -> str:
    return """Извлеки данные заказа Amelia Flowers из русской переписки.
Верни только JSON без Markdown. Не выдумывай неизвестные поля.
Поля: occasion, budget, colors, forbidden_flowers, fulfillment_type(delivery/pickup), delivery_date(today/tomorrow), delivery_time(HH:MM), address, sender_name, sender_phone, recipient_name, recipient_phone, payment_method(transfer/cash/crypto), postcard_text, anonymous, photo_report_requested.

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
    merged_card = merge_order_state(OrderCard(), regex_state)
    merged_card = merge_order_state(merged_card, llm_state)
    data = merged_card.to_dict()
    data.pop("admin_request_sent", None)
    data.pop("client_summary_sent", None)
    return OrderState(**data)
