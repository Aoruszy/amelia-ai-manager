from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from amelia_manager.events import EventName

SAFE_PAYLOAD_KEYS = {
    "has_media",
    "next_step",
    "intent",
    "confidence",
    "llm_used",
    "field_code",
    "budget",
    "fulfillment_type",
    "risk_category",
    "risk_level",
    "reason",
    "reasons",
    "retry_succeeded",
    "stage",
    "source_name",
    "kind",
    "step_code",
}


def sanitize_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    return {key: value for key, value in payload.items() if key in SAFE_PAYLOAD_KEYS}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = sanitize_payload(getattr(record, "payload", {}))
        event = getattr(record, "event", None)
        if isinstance(event, EventName):
            event = event.value
        data = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "event": event or record.getMessage(),
        }
        if hasattr(record, "client_id"):
            data["client_id"] = getattr(record, "client_id")
        if hasattr(record, "order_id"):
            data["order_id"] = getattr(record, "order_id")
        data.update(payload)
        return json.dumps(data, ensure_ascii=False, default=str)


def configure_logging(log_level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("amelia_manager")
    root.handlers = [handler]
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root.propagate = False


class EventRecorder:
    def __init__(self, repo, *, logger: logging.Logger | None = None) -> None:
        self.repo = repo
        self.logger = logger or logging.getLogger("amelia_manager.events")

    def record(
        self,
        event: EventName,
        *,
        client_id: int | None = None,
        order_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        safe_payload = sanitize_payload(payload)
        try:
            if client_id is not None:
                self.repo.record_event(client_id=client_id, order_id=order_id, event=event, payload=safe_payload)
        except Exception as exc:  # noqa: BLE001 - metrics must never break dialogue
            self.logger.warning(
                "event_record_failed",
                extra={"event": "event_record_failed", "client_id": client_id, "order_id": order_id, "payload": {"reason": repr(exc)}},
            )
        self.logger.info(event.value, extra={"event": event, "client_id": client_id, "order_id": order_id, "payload": safe_payload})
