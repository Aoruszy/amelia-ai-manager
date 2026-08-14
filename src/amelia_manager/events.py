from __future__ import annotations

from enum import StrEnum


class EventName(StrEnum):
    DIALOG_STARTED = "dialog_started"
    MESSAGE_RECEIVED = "message_received"
    REPLY_SENT = "reply_sent"
    STEP_COMPLETED = "step_completed"
    CASE_PATCH_IGNORED = "case_patch_ignored"
    ORDER_READY = "order_ready"
    ADMIN_REQUEST_SENT = "admin_request_sent"
    ESCALATED = "escalated"
    SAFETY_TRIGGERED = "safety_triggered"
    LLM_FAILED = "llm_failed"
    PARSE_FAILED = "parse_failed"
    CATALOG_UPDATED = "catalog_updated"
    ORDER_SCOPE_DECIDED = "order_scope_decided"
    NEW_ORDER_STARTED = "new_order_started"
    SCOPE_MISMATCH = "scope_mismatch"
    STOCK_SOURCE_DEGRADED = "stock_source_degraded"
    OFF_HOURS_REPLY = "off_hours_reply"
    FOLLOWUP_SCHEDULED = "followup_scheduled"
    FOLLOWUP_SENT = "followup_sent"
    FOLLOWUP_CANCELLED = "followup_cancelled"
    FOLLOWUP_REPLIED = "followup_replied"
    REMINDER_SENT = "reminder_sent"
    OPT_OUT = "opt_out"
    STATUS_ANSWERED = "status_answered"
    ORDER_STATUS_CHANGED = "order_status_changed"
    BOT_PAUSED = "bot_paused"
    BOT_RESUMED = "bot_resumed"
    CARD_EDITED_MANUALLY = "card_edited_manually"
