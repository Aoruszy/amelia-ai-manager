from __future__ import annotations

from enum import StrEnum


class EventName(StrEnum):
    DIALOG_STARTED = "dialog_started"
    MESSAGE_RECEIVED = "message_received"
    REPLY_SENT = "reply_sent"
    STEP_COMPLETED = "step_completed"
    ORDER_READY = "order_ready"
    ADMIN_REQUEST_SENT = "admin_request_sent"
    ESCALATED = "escalated"
    SAFETY_TRIGGERED = "safety_triggered"
    LLM_FAILED = "llm_failed"
    STOCK_SOURCE_DEGRADED = "stock_source_degraded"
    OFF_HOURS_REPLY = "off_hours_reply"
