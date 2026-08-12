from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from amelia_manager.company_profile import CompanyProfile
from amelia_manager.order_state import OrderState


@dataclass(frozen=True)
class OrderCard:
    occasion: str | None = None
    budget: int | None = None
    colors: list[str] = field(default_factory=list)
    forbidden_flowers: list[str] = field(default_factory=list)
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
    custom_fields: dict[str, Any] = field(default_factory=dict)
    admin_request_sent: bool = False
    client_summary_sent: bool = False
    sheet_row_written: bool = False

    @property
    def product_preferences(self) -> list[str]:
        return self.colors

    @property
    def excluded_items(self) -> list[str]:
        return self.forbidden_flowers

    @property
    def note_text(self) -> str | None:
        return self.postcard_text

    def is_ready_for_admin_request(self) -> bool:
        common_ready = all(
            [
                self.budget,
                self.colors,
                self.fulfillment_type,
                self.delivery_date,
                self.delivery_time,
                self.sender_name,
                self.sender_phone,
            ]
        )
        if not common_ready:
            return False
        if self.fulfillment_type == "pickup":
            return _is_pickup_time_within_shop_hours(self.delivery_time)
        if self.fulfillment_type == "delivery":
            return bool(self.address and self.recipient_name and self.recipient_phone and self.payment_method)
        return False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrderCard":
        fields = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in data.items() if key in fields})


def merge_order_state(existing: OrderCard, state: OrderState) -> OrderCard:
    fulfillment_type = state.fulfillment_type or existing.fulfillment_type
    changed_to_delivery = existing.fulfillment_type == "pickup" and state.fulfillment_type == "delivery"
    changed_to_pickup = existing.fulfillment_type == "delivery" and state.fulfillment_type == "pickup"
    return OrderCard(
        occasion=state.occasion or existing.occasion,
        budget=state.budget or existing.budget,
        colors=_merge_list(existing.colors, state.colors),
        forbidden_flowers=_merge_list(existing.forbidden_flowers, state.forbidden_flowers),
        fulfillment_type=fulfillment_type,
        delivery_date=state.delivery_date or existing.delivery_date,
        delivery_time=state.delivery_time or (None if changed_to_delivery else existing.delivery_time),
        address=state.address or (None if changed_to_pickup else existing.address),
        sender_name=state.sender_name or existing.sender_name,
        sender_phone=state.sender_phone or existing.sender_phone,
        recipient_name=state.recipient_name or existing.recipient_name,
        recipient_phone=state.recipient_phone or existing.recipient_phone,
        payment_method=state.payment_method or existing.payment_method,
        postcard_text=state.postcard_text or existing.postcard_text,
        anonymous=state.anonymous if state.anonymous is not None else existing.anonymous,
        photo_report_requested=(
            state.photo_report_requested
            if state.photo_report_requested is not None
            else existing.photo_report_requested
        ),
        custom_fields={
            **existing.custom_fields,
            **{key: value for key, value in state.custom_fields.items() if value not in (None, "", [], {})},
        },
        admin_request_sent=existing.admin_request_sent,
        client_summary_sent=existing.client_summary_sent,
        sheet_row_written=existing.sheet_row_written,
    )


def merge_order_patch(existing: OrderCard, patch: dict[str, Any]) -> OrderCard:
    if not patch:
        return existing
    allowed = set(OrderCard.__dataclass_fields__.keys()) - {"admin_request_sent", "client_summary_sent"}
    cleaned = {key: value for key, value in patch.items() if key in allowed and value not in (None, "", [], {})}
    if "custom_fields" in cleaned and isinstance(cleaned["custom_fields"], dict):
        cleaned["custom_fields"] = {**existing.custom_fields, **cleaned["custom_fields"]}
    if not cleaned:
        return existing
    return OrderCard.from_dict({**existing.to_dict(), **cleaned})


def _merge_list(left: list[str], right: list[str]) -> list[str]:
    result = list(left)
    for item in right:
        if item not in result:
            result.append(item)
    return result


def _is_pickup_time_within_shop_hours(value: str | None) -> bool:
    if not value:
        return False
    match = re.search(r"\b(\d{1,2})[:.](\d{2})\b", value)
    if not match:
        return True
    hour = int(match.group(1))
    minute = int(match.group(2))
    return (hour, minute) >= (9, 0) and (hour, minute) <= (20, 0)


def is_ready_for_profile_case(card: OrderCard, profile: CompanyProfile, case_type: str) -> bool:
    required_codes = profile.required_field_codes(case_type)
    if not required_codes:
        return False
    return all(_business_field_value(card, code) not in (None, "", [], {}) for code in required_codes)


def _business_field_value(card: OrderCard, code: str) -> object:
    mapping = {
        "budget": card.budget,
        "date": card.delivery_date,
        "time": card.delivery_time,
        "delivery_address": card.address,
        "address": card.address,
        "recipient_name": card.recipient_name,
        "recipient_phone": card.recipient_phone,
        "customer_name": card.sender_name,
        "sender_name": card.sender_name,
        "customer_phone": card.sender_phone,
        "sender_phone": card.sender_phone,
        "payment_method": card.payment_method,
        "product_preferences": card.colors,
        "preferences": card.colors,
        "postcard_text": card.postcard_text,
        "anonymous": card.anonymous,
        "photo_report_requested": card.photo_report_requested,
        "fulfillment_type": card.fulfillment_type,
    }
    return mapping.get(code, card.custom_fields.get(code))
