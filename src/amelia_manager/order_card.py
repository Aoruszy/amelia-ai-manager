from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from amelia_manager.company_profile import CompanyProfile
from amelia_manager.order_fields import card_field_for_profile_code, normalize_order_patch_keys, profile_code_for_card_field
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
    delivery_date = _valid_delivery_date(state.delivery_date) or existing.delivery_date
    delivery_time = _valid_delivery_time(state.delivery_time)
    fulfillment_type = _valid_fulfillment_type(state.fulfillment_type) or existing.fulfillment_type
    changed_to_delivery = existing.fulfillment_type == "pickup" and state.fulfillment_type == "delivery"
    changed_to_pickup = existing.fulfillment_type == "delivery" and state.fulfillment_type == "pickup"
    return OrderCard(
        occasion=state.occasion or existing.occasion,
        budget=state.budget or existing.budget,
        colors=_merge_list(existing.colors, state.colors),
        forbidden_flowers=_merge_list(existing.forbidden_flowers, state.forbidden_flowers),
        fulfillment_type=fulfillment_type,
        delivery_date=delivery_date,
        delivery_time=delivery_time or (None if changed_to_delivery else existing.delivery_time),
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
    normalized, _unknown = normalize_order_patch_keys(patch, allowed_fields=allowed)
    cleaned = {key: value for key, value in normalized.items() if value not in (None, "", [], {})}
    cleaned = _drop_invalid_order_values(cleaned)
    if "custom_fields" in cleaned and isinstance(cleaned["custom_fields"], dict):
        cleaned["custom_fields"] = {**existing.custom_fields, **cleaned["custom_fields"]}
    if not cleaned:
        return existing
    return OrderCard.from_dict({**existing.to_dict(), **cleaned})


def applied_order_patch_field_codes(before: OrderCard, after: OrderCard, patch: dict[str, Any]) -> list[str]:
    allowed = set(OrderCard.__dataclass_fields__.keys()) - {"admin_request_sent", "client_summary_sent"}
    changed: list[str] = []
    for original_code, value in patch.items():
        field = normalize_order_patch_keys({original_code: value}, allowed_fields=allowed)[0]
        if not field:
            continue
        card_field = next(iter(field.keys()))
        if value in (None, "", [], {}):
            continue
        if getattr(before, card_field, None) != getattr(after, card_field, None):
            changed.append(profile_code_for_card_field(card_field))
    return list(dict.fromkeys(changed))


def unapplied_order_patch_field_codes(patch: dict[str, Any]) -> list[str]:
    allowed = set(OrderCard.__dataclass_fields__.keys()) - {"admin_request_sent", "client_summary_sent"}
    normalized, unknown = normalize_order_patch_keys(patch, allowed_fields=allowed)
    invalid = invalid_order_values(normalized)
    return list(dict.fromkeys([*unknown, *invalid]))


def invalid_order_values(values: dict[str, Any]) -> list[str]:
    invalid: list[str] = []
    for field_name, validator in {
        "delivery_date": _valid_delivery_date,
        "delivery_time": _valid_delivery_time,
        "fulfillment_type": _valid_fulfillment_type,
    }.items():
        if field_name in values and values[field_name] not in (None, [], {}) and validator(values[field_name]) is None:
            invalid.append(field_name)
    return invalid


def invalid_order_state_field_codes(state: OrderState) -> list[str]:
    return invalid_order_values({
        "delivery_date": state.delivery_date,
        "delivery_time": state.delivery_time,
        "fulfillment_type": state.fulfillment_type,
    })


def _drop_invalid_order_values(values: dict[str, Any]) -> dict[str, Any]:
    invalid = set(invalid_order_values(values))
    return {key: value for key, value in values.items() if key not in invalid}


def _valid_delivery_date(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    return text


def _valid_delivery_time(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(\d{2}):(\d{2})", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return text


def _valid_fulfillment_type(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    return value if value in {"pickup", "delivery"} else None


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


def format_budget_display(card: OrderCard) -> str | None:
    range_value = card.custom_fields.get("budget_range")
    if isinstance(range_value, str) and range_value.strip():
        normalized = range_value.strip().replace("—", "–").replace("-", "–")
        normalized = re.sub(r"\s*–\s*", "–", normalized)
        if not re.search(r"(?:₽|руб|р\b)", normalized.lower()):
            normalized = f"{normalized} ₽"
        return normalized
    if card.budget:
        return f"{card.budget} ₽"
    return None


def is_ready_for_profile_case(card: OrderCard, profile: CompanyProfile, case_type: str) -> bool:
    required_codes = profile.required_field_codes(case_type)
    if not required_codes:
        return False
    return all(_business_field_value(card, code) not in (None, "", [], {}) for code in required_codes)


def _business_field_value(card: OrderCard, code: str) -> object:
    field = card_field_for_profile_code(code)
    if field:
        return getattr(card, field)
    return card.custom_fields.get(code)
