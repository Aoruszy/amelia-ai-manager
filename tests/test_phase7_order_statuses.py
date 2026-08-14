from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amelia_manager.admin import create_app
from amelia_manager.company_profile import load_company_profile
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.events import EventName
from amelia_manager.metrics import calculate_metrics
from amelia_manager.order_card import OrderCard
from amelia_manager.outbound import OutboundKind, build_order_status_reply
from amelia_manager.telegram_runtime import build_admin_order_request_if_needed


def _repo(tmp_path: Path) -> SQLiteRepository:
    repo = SQLiteRepository(tmp_path / "statuses.sqlite3")
    repo.initialize()
    return repo


def _auth(username: str = "admin", password: str = "secret") -> dict[str, str]:
    import base64

    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _admin_app(tmp_path: Path) -> tuple[TestClient, SQLiteRepository]:
    db_path = tmp_path / "statuses-admin.sqlite3"
    repo = SQLiteRepository(db_path)
    repo.initialize()
    settings = Settings(database_url=f"sqlite:///{db_path}", admin_username="admin", admin_password="secret")
    return TestClient(create_app(settings=settings)), repo


def _ready_card() -> OrderCard:
    return OrderCard(
        budget=5000,
        colors=["нежный"],
        fulfillment_type="pickup",
        delivery_date="tomorrow",
        delivery_time="12:00",
        sender_name="Даня",
        sender_phone="89990000001",
        payment_method="cash",
    )


def test_new_orders_start_in_draft_status_and_submitted_is_set_when_admin_request_is_built(tmp_path):
    repo = _repo(tmp_path)
    client = repo.upsert_client(telegram_id=101, username="buyer")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(order_id=order.id, card=_ready_card())

    assert order.status == "draft"

    text = build_admin_order_request_if_needed(repo, order=repo.get_order_by_id(order.id), client_label="buyer")

    saved = repo.get_order_by_id(order.id)
    assert text is not None
    assert saved.status == "submitted"
    events = repo.list_events(client_id=client.id, event=EventName.ORDER_STATUS_CHANGED)
    assert len(events) == 1
    payload = json.loads(events[0].payload_json)
    assert payload == {"old_status": "draft", "new_status": "submitted", "changed_by": "bot"}


def test_repository_validates_and_records_manual_status_transition(tmp_path):
    repo = _repo(tmp_path)
    client = repo.upsert_client(telegram_id=102, username="buyer")
    order = repo.get_or_create_active_order(client_id=client.id)

    with pytest.raises(ValueError, match="invalid order status"):
        repo.update_order_status(order_id=order.id, status="unknown", changed_by="admin")

    updated = repo.update_order_status(order_id=order.id, status="confirmed", changed_by="admin")

    assert updated.status == "confirmed"
    event = repo.list_events(client_id=client.id, event=EventName.ORDER_STATUS_CHANGED)[0]
    payload = json.loads(event.payload_json)
    assert payload == {"old_status": "draft", "new_status": "confirmed", "changed_by": "admin"}


def test_admin_detail_shows_status_controls_and_changes_status_without_pii_payload(tmp_path):
    web, repo = _admin_app(tmp_path)
    client = repo.upsert_client(telegram_id=103, username="buyer")
    order = repo.get_or_create_active_order(client_id=client.id)

    page = web.get(f"/clients/{client.id}", headers=_auth())
    assert page.status_code == 200
    assert "Статус заказа" in page.text
    assert "Подтверждён" in page.text

    response = web.post(
        f"/clients/{client.id}/orders/{order.id}/status",
        headers=_auth(),
        data={"status": "confirmed"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert repo.get_order_by_id(order.id).status == "confirmed"
    payload = repo.list_events(client_id=client.id, event=EventName.ORDER_STATUS_CHANGED)[0].payload_json
    assert "confirmed" in payload
    assert "103" not in payload
    assert "buyer" not in payload


def test_status_question_uses_order_status_labels(tmp_path):
    repo = _repo(tmp_path)
    client = repo.upsert_client(telegram_id=104, username="buyer")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_status(order_id=order.id, status="ready", changed_by="admin")

    reply = build_order_status_reply(repo, client_id=client.id, company_profile=load_company_profile())

    assert "готов" in reply.lower()
    assert "заказ ещё оформляется" not in reply.lower()


def test_status_metrics_count_current_statuses_and_transitions(tmp_path):
    repo = _repo(tmp_path)
    now = datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=10)
    c1 = repo.upsert_client(telegram_id=105, username="one")
    c2 = repo.upsert_client(telegram_id=106, username="two")
    o1 = repo.get_or_create_active_order(client_id=c1.id)
    o2 = repo.get_or_create_active_order(client_id=c2.id)
    repo.update_order_status(order_id=o1.id, status="confirmed", changed_by="admin", changed_at=now)
    repo.update_order_status(order_id=o2.id, status="ready", changed_by="admin", changed_at=now)

    metrics = calculate_metrics(repo, date_from=date.today(), date_to=date.today())

    assert metrics["orders"]["current_by_status"]["confirmed"] == 1
    assert metrics["orders"]["current_by_status"]["ready"] == 1
    assert metrics["orders"]["transitions"]["confirmed"] == 1
    assert metrics["orders"]["transitions"]["ready"] == 1


def test_confirmed_and_ready_statuses_schedule_existing_outbound_notifications(tmp_path):
    repo = _repo(tmp_path)
    client = repo.upsert_client(telegram_id=107, username="buyer")
    order = repo.get_or_create_active_order(client_id=client.id)
    now = datetime(2026, 8, 14, 10, 0, 0)

    repo.update_order_status(order_id=order.id, status="confirmed", changed_by="admin", changed_at=now)
    repo.update_order_status(order_id=order.id, status="ready", changed_by="admin", changed_at=now + timedelta(minutes=1))

    due = repo.list_due_outbound(now=now + timedelta(minutes=2))
    assert [item.kind for item in due] == [OutboundKind.ORDER_CONFIRMED.value, OutboundKind.ORDER_READY.value]
