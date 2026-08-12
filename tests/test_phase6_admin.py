from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from amelia_manager.admin import create_app
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.events import EventName
from amelia_manager.order_card import OrderCard


def _auth() -> dict[str, str]:
    token = base64.b64encode(b"admin:secret").decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _app(tmp_path: Path) -> tuple[TestClient, SQLiteRepository]:
    db_path = tmp_path / "admin.sqlite3"
    repo = SQLiteRepository(db_path)
    repo.initialize()
    settings = Settings(database_url=f"sqlite:///{db_path}", admin_username="admin", admin_password="secret")
    return TestClient(create_app(settings=settings)), repo


def test_admin_requires_basic_auth(tmp_path):
    client, _repo = _app(tmp_path)

    response = client.get("/")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


def test_admin_dialogue_list_filters_and_hides_telegram_ids_from_urls(tmp_path):
    client, repo = _app(tmp_path)
    paused = repo.upsert_client(telegram_id=111, username="paused_user")
    active = repo.upsert_client(telegram_id=222, username="active_user")
    repo.add_message(client_id=paused.id, direction="in", text="нужен букет")
    repo.add_message(client_id=active.id, direction="in", text="привет")
    repo.pause_client(client_id=paused.id, paused_by="manual", reason="manual")

    response = client.get("/?filter=paused", headers=_auth())

    assert response.status_code == 200
    assert "paused_user" in response.text
    assert "active_user" not in response.text
    assert f"/clients/{paused.id}" in response.text
    assert "/clients/111" not in response.text


def test_admin_dialogue_detail_shows_messages_card_and_pause_actions(tmp_path):
    client, repo = _app(tmp_path)
    record = repo.upsert_client(telegram_id=111, username="user1")
    order = repo.get_or_create_active_order(client_id=record.id)
    repo.update_order_card(order_id=order.id, card=OrderCard(budget=5000, colors=["белые"], fulfillment_type="pickup"))
    repo.add_message(client_id=record.id, direction="in", text="хочу букет")
    repo.add_message(client_id=record.id, direction="out", text="Подскажите бюджет")

    response = client.get(f"/clients/{record.id}", headers=_auth())

    assert response.status_code == 200
    assert "хочу букет" in response.text
    assert "Подскажите бюджет" in response.text
    assert "5000" in response.text
    assert "Перехватить" in response.text
    assert "telegram_id=111" not in response.text


def test_admin_pause_resume_and_card_edit_write_events(tmp_path):
    client, repo = _app(tmp_path)
    record = repo.upsert_client(telegram_id=111, username="user1")
    order = repo.get_or_create_active_order(client_id=record.id)

    pause = client.post(f"/clients/{record.id}/pause", headers=_auth(), follow_redirects=False)
    assert pause.status_code == 303
    assert repo.get_client_by_id(record.id).bot_paused_at is not None

    resume = client.post(f"/clients/{record.id}/resume", headers=_auth(), follow_redirects=False)
    assert resume.status_code == 303
    assert repo.get_client_by_id(record.id).bot_paused_at is None

    edit = client.post(
        f"/clients/{record.id}/card",
        headers=_auth(),
        data={"budget": "7000", "fulfillment_type": "delivery", "colors": "белые, розовые"},
        follow_redirects=False,
    )
    assert edit.status_code == 303
    saved = repo.get_order_by_id(order.id).card
    assert saved.budget == 7000
    assert saved.fulfillment_type == "delivery"
    assert saved.colors == ["белые", "розовые"]
    event = repo.list_events(client_id=record.id, event=EventName.CARD_EDITED_MANUALLY)[0]
    assert "budget" in event.payload_json
    assert "7000" not in event.payload_json


def test_admin_metrics_page_shows_funnel_for_selected_period(tmp_path):
    client, repo = _app(tmp_path)
    record = repo.upsert_client(telegram_id=111, username=None)
    repo.record_event(client_id=record.id, order_id=None, event=EventName.DIALOG_STARTED)
    repo.record_event(client_id=record.id, order_id=None, event=EventName.ADMIN_REQUEST_SENT)

    response = client.get("/metrics?days=30", headers=_auth())

    assert response.status_code == 200
    assert "Воронка" in response.text
    assert "Конверсия" in response.text
    assert "30 дней" in response.text
