from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ModelDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: str | None = None
    emotion: str | None = None
    reply: str
    case_patch: dict[str, Any] = Field(default_factory=dict)
    next_step: str | None = None
    needs_human: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1)
    order_scope: str = "continue"

    @field_validator("order_scope", mode="before")
    @classmethod
    def _valid_order_scope(cls, value: object) -> str:
        if value in {"continue", "new_order", "unrelated"}:
            return str(value)
        return "continue"


def parse_model_decision(raw: str) -> ModelDecision | None:
    text = raw.strip()
    if not text.startswith("{") and "{" not in text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        if not isinstance(data, dict) or "reply" not in data:
            return None
        return ModelDecision.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
        return None
