from __future__ import annotations

from typing import Any

from amelia_manager.order_state import OrderState

PROFILE_FIELD_TO_CARD_FIELD: dict[str, str] = {
    "budget": "budget",
    "date": "delivery_date",
    "delivery_date": "delivery_date",
    "time": "delivery_time",
    "delivery_time": "delivery_time",
    "delivery_address": "address",
    "address": "address",
    "recipient_name": "recipient_name",
    "recipient_phone": "recipient_phone",
    "customer_name": "sender_name",
    "sender_name": "sender_name",
    "customer_phone": "sender_phone",
    "sender_phone": "sender_phone",
    "payment_method": "payment_method",
    "product_preferences": "colors",
    "preferences": "colors",
    "colors": "colors",
    "postcard_text": "postcard_text",
    "anonymous": "anonymous",
    "photo_report_requested": "photo_report_requested",
    "fulfillment_type": "fulfillment_type",
}

CARD_FIELD_TO_PROFILE_FIELD: dict[str, str] = {
    "delivery_date": "date",
    "delivery_time": "time",
    "address": "delivery_address",
    "sender_name": "customer_name",
    "sender_phone": "customer_phone",
    "colors": "product_preferences",
    **{field: field for field in OrderState.__dataclass_fields__.keys() if field not in {"delivery_date", "delivery_time", "address", "sender_name", "sender_phone", "colors"}},
}


def card_field_for_profile_code(code: str) -> str | None:
    return PROFILE_FIELD_TO_CARD_FIELD.get(code)


def profile_code_for_card_field(field: str) -> str:
    return CARD_FIELD_TO_PROFILE_FIELD.get(field, field)


def normalize_order_patch_keys(patch: dict[str, Any], *, allowed_fields: set[str]) -> tuple[dict[str, Any], list[str]]:
    normalized: dict[str, Any] = {}
    unknown: list[str] = []
    for key, value in patch.items():
        field = card_field_for_profile_code(key) or (key if key in allowed_fields else None)
        if field is None or field not in allowed_fields:
            unknown.append(key)
            continue
        normalized[field] = value
    return normalized, unknown
