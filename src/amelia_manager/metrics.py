from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from amelia_manager.events import EventName


def calculate_metrics(repo, *, date_from: date, date_to: date) -> dict[str, Any]:
    rows = repo.list_events(date_from=date_from, date_to=date_to)
    by_event = defaultdict(list)
    for row in rows:
        by_event[row.event].append(row)

    dialogs = _clients_for(by_event[EventName.DIALOG_STARTED.value])
    admin_requests = _clients_for(by_event[EventName.ADMIN_REQUEST_SENT.value])
    escalated = _clients_for(by_event[EventName.ESCALATED.value])
    safety_clients = _clients_for(by_event[EventName.SAFETY_TRIGGERED.value])
    llm_failed_clients = _clients_for(by_event[EventName.LLM_FAILED.value])
    parse_failed_clients = _clients_for(by_event[EventName.PARSE_FAILED.value])
    off_hours_clients = _clients_for(by_event[EventName.OFF_HOURS_REPLY.value])
    followup_sent_clients = _clients_for(by_event[EventName.FOLLOWUP_SENT.value])
    followup_replied_clients = _clients_for(by_event[EventName.FOLLOWUP_REPLIED.value])
    opt_out_clients = _clients_for(by_event[EventName.OPT_OUT.value])
    dialog_count = len(dialogs)

    confidence_values = []
    for row in by_event[EventName.REPLY_SENT.value]:
        value = _payload(row).get("confidence")
        if isinstance(value, int | float):
            confidence_values.append(float(value))

    return {
        "conversion": {
            "dialogs": dialog_count,
            "admin_requests": len(admin_requests),
            "rate": _rate(len(admin_requests & dialogs), dialog_count),
        },
        "funnel": _funnel(by_event[EventName.STEP_COMPLETED.value]),
        "escalations": {
            "dialogs": len(escalated),
            "rate": _rate(len(escalated & dialogs), dialog_count),
            "by_risk_category": _count_payload_value(by_event[EventName.ESCALATED.value], "risk_category"),
        },
        "quality": {
            "safety_trigger_rate": _rate(len(safety_clients & dialogs), dialog_count),
            "retry_success_rate": _rate(_count_retry_success(by_event[EventName.SAFETY_TRIGGERED.value]), len(by_event[EventName.SAFETY_TRIGGERED.value])),
            "llm_failed_rate": _rate(len(llm_failed_clients & dialogs), dialog_count),
            "parse_failed_rate": _rate(len(parse_failed_clients & dialogs), dialog_count),
            "parse_retry_success_rate": _rate(_count_retry_success(by_event[EventName.PARSE_FAILED.value]), len(by_event[EventName.PARSE_FAILED.value])),
            "confidence_distribution": _confidence_distribution(confidence_values),
        },
        "ops": {
            "reply_latency_seconds": _reply_latency(by_event[EventName.MESSAGE_RECEIVED.value], by_event[EventName.REPLY_SENT.value]),
            "off_hours_rate": _rate(len(off_hours_clients & dialogs), dialog_count),
            "average_budget": _average_budget(by_event[EventName.ORDER_READY.value]),
        },
        "outbound": {
            "followups_sent": len(by_event[EventName.FOLLOWUP_SENT.value]),
            "followup_replies": len(by_event[EventName.FOLLOWUP_REPLIED.value]),
            "followup_reply_rate": _rate(len(followup_replied_clients), len(followup_sent_clients)),
            "followup_to_admin_request_rate": _rate(len(followup_replied_clients & admin_requests), len(followup_replied_clients)),
            "opt_outs": len(opt_out_clients),
            "opt_out_rate": _rate(len(opt_out_clients & dialogs), dialog_count),
        },
    }


def _payload(row) -> dict[str, Any]:
    try:
        data = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _clients_for(rows) -> set[int]:
    return {int(row.client_id) for row in rows}


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _funnel(rows) -> dict[str, int]:
    result: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        field_code = _payload(row).get("field_code")
        if field_code:
            result[str(field_code)].add(row.client_id)
    return {field: len(client_ids) for field, client_ids in result.items()}


def _count_payload_value(rows, key: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        value = _payload(row).get(key)
        if value:
            counts[str(value)] += 1
    return dict(counts)


def _count_retry_success(rows) -> int:
    return sum(1 for row in rows if _payload(row).get("retry_succeeded") is True)


def _confidence_distribution(values: list[float]) -> dict[str, int]:
    buckets = {"0-0.5": 0, "0.5-0.7": 0, "0.7-1.0": 0}
    for value in values:
        if value < 0.5:
            buckets["0-0.5"] += 1
        elif value < 0.7:
            buckets["0.5-0.7"] += 1
        else:
            buckets["0.7-1.0"] += 1
    return buckets


def _reply_latency(message_rows, reply_rows) -> dict[str, float | None]:
    by_client: dict[int, list[datetime]] = defaultdict(list)
    for row in message_rows:
        by_client[row.client_id].append(_parse_created_at(row.created_at))
    latencies: list[float] = []
    for row in reply_rows:
        reply_at = _parse_created_at(row.created_at)
        candidates = [ts for ts in by_client.get(row.client_id, []) if ts <= reply_at]
        if candidates:
            latencies.append((reply_at - max(candidates)).total_seconds())
    if not latencies:
        return {"median": None, "p95": None}
    return {"median": statistics.median(latencies), "p95": _percentile(latencies, 0.95)}


def _parse_created_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _average_budget(rows) -> float | None:
    budgets = []
    for row in rows:
        value = _payload(row).get("budget")
        if isinstance(value, int | float):
            budgets.append(float(value))
    return statistics.mean(budgets) if budgets else None
