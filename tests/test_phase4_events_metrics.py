from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.events import EventName
from amelia_manager.metrics import calculate_metrics
from amelia_manager.observability import JsonFormatter, EventRecorder


def test_repository_records_events_without_pii_and_retention(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="dummy")
    order = repo.get_or_create_active_order(client_id=client.id)

    repo.record_event(client_id=client.id, order_id=order.id, event=EventName.MESSAGE_RECEIVED, payload={"has_media": False, "text": "SECRET"})
    rows = repo.list_events()

    assert rows[0].event == EventName.MESSAGE_RECEIVED
    payload = json.loads(rows[0].payload_json)
    assert "text" not in payload
    assert payload == {"has_media": False}

    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=91)
    repo.record_event(client_id=client.id, order_id=None, event=EventName.DIALOG_STARTED, payload={}, created_at=old)
    result = repo.cleanup_pii_older_than(retention_days=30, now=datetime.now(timezone.utc))
    assert result.deleted_events >= 1
    assert all(row.event != EventName.DIALOG_STARTED for row in repo.list_events())


def test_json_formatter_emits_structured_event_without_message_text():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="amelia_manager",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ignored free text",
        args=(),
        exc_info=None,
    )
    record.event = EventName.REPLY_SENT
    record.client_id = 10
    record.order_id = 20
    record.payload = {"intent": "order", "text": "SECRET"}

    data = json.loads(formatter.format(record))

    assert data["event"] == "reply_sent"
    assert data["client_id"] == 10
    assert data["order_id"] == 20
    assert data["intent"] == "order"
    assert "text" not in data
    assert "time" in data


def test_event_recorder_never_raises_when_db_write_fails(caplog):
    class BrokenRepo:
        def record_event(self, **kwargs):
            raise RuntimeError("db down")

    recorder = EventRecorder(BrokenRepo())

    with caplog.at_level(logging.WARNING):
        recorder.record(EventName.REPLY_SENT, client_id=1, order_id=2, payload={"next_step": "ask_budget"})

    assert "event_record_failed" in caplog.text


def test_metrics_calculate_conversion_funnel_quality_and_ops(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    c1 = repo.upsert_client(telegram_id=1, username=None)
    c2 = repo.upsert_client(telegram_id=2, username=None)
    start = datetime(2026, 8, 1, 10, 0, 0)
    repo.record_event(client_id=c1.id, order_id=1, event=EventName.DIALOG_STARTED, payload={}, created_at=start)
    repo.record_event(client_id=c1.id, order_id=1, event=EventName.MESSAGE_RECEIVED, payload={"has_media": False}, created_at=start)
    repo.record_event(client_id=c1.id, order_id=1, event=EventName.STEP_COMPLETED, payload={"field_code": "budget"}, created_at=start + timedelta(seconds=2))
    repo.record_event(client_id=c1.id, order_id=1, event=EventName.REPLY_SENT, payload={"confidence": 0.8, "intent": "order"}, created_at=start + timedelta(seconds=10))
    repo.record_event(client_id=c1.id, order_id=1, event=EventName.ORDER_READY, payload={"budget": 5000, "fulfillment_type": "pickup"}, created_at=start + timedelta(minutes=1))
    repo.record_event(client_id=c1.id, order_id=1, event=EventName.ADMIN_REQUEST_SENT, payload={}, created_at=start + timedelta(minutes=2))
    repo.record_event(client_id=c2.id, order_id=2, event=EventName.DIALOG_STARTED, payload={}, created_at=start)
    repo.record_event(client_id=c2.id, order_id=2, event=EventName.ESCALATED, payload={"risk_category": "guarantee_request", "risk_level": "medium"}, created_at=start)
    repo.record_event(client_id=c2.id, order_id=2, event=EventName.SAFETY_TRIGGERED, payload={"reasons": ["x"], "retry_succeeded": True}, created_at=start)
    repo.record_event(client_id=c2.id, order_id=2, event=EventName.LLM_FAILED, payload={"stage": "eval"}, created_at=start)
    repo.record_event(client_id=c2.id, order_id=2, event=EventName.OFF_HOURS_REPLY, payload={}, created_at=start)
    repo.record_event(client_id=c1.id, order_id=1, event=EventName.FOLLOWUP_SENT, payload={"kind": "followup_1"}, created_at=start)
    repo.record_event(client_id=c1.id, order_id=1, event=EventName.FOLLOWUP_REPLIED, payload={"kind": "followup_1"}, created_at=start)
    repo.record_event(client_id=c2.id, order_id=2, event=EventName.FOLLOWUP_SENT, payload={"kind": "followup_1"}, created_at=start)
    repo.record_event(client_id=c2.id, order_id=2, event=EventName.OPT_OUT, payload={}, created_at=start)

    metrics = calculate_metrics(repo, date_from=start.date(), date_to=start.date())

    assert metrics["conversion"]["dialogs"] == 2
    assert metrics["conversion"]["admin_requests"] == 1
    assert metrics["conversion"]["rate"] == 0.5
    assert metrics["funnel"]["budget"] == 1
    assert metrics["escalations"]["rate"] == 0.5
    assert metrics["escalations"]["by_risk_category"]["guarantee_request"] == 1
    assert metrics["quality"]["safety_trigger_rate"] == 0.5
    assert metrics["quality"]["retry_success_rate"] == 1.0
    assert metrics["quality"]["llm_failed_rate"] == 0.5
    assert metrics["quality"]["confidence_distribution"]["0.7-1.0"] == 1
    assert metrics["ops"]["reply_latency_seconds"]["median"] == 10
    assert metrics["ops"]["off_hours_rate"] == 0.5
    assert metrics["ops"]["average_budget"] == 5000
    assert metrics["outbound"]["followup_reply_rate"] == 0.5
    assert metrics["outbound"]["followup_to_admin_request_rate"] == 1.0
    assert metrics["outbound"]["opt_out_rate"] == 0.5


def test_metrics_empty_period_is_zero_safe(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()

    metrics = calculate_metrics(repo, date_from=datetime(2026, 8, 1).date(), date_to=datetime(2026, 8, 7).date())

    assert metrics["conversion"]["dialogs"] == 0
    assert metrics["conversion"]["rate"] == 0.0
    assert metrics["funnel"] == {}
