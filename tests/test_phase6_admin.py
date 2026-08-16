from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from amelia_manager.admin import create_app
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.events import EventName
from amelia_manager.order_card import OrderCard


def _auth(username: str = "admin", password: str = "secret") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _post_headers() -> dict[str, str]:
    return {**_auth(), "Origin": "http://testserver"}


def _app(tmp_path: Path) -> tuple[TestClient, SQLiteRepository]:
    db_path = tmp_path / "admin.sqlite3"
    repo = SQLiteRepository(db_path)
    repo.initialize()
    settings = Settings(database_url=f"sqlite:///{db_path}", admin_username="admin", admin_password="secret")
    return TestClient(create_app(settings=settings)), repo


def test_admin_requires_explicit_credentials(tmp_path):
    db_path = tmp_path / "admin.sqlite3"
    settings = Settings(database_url=f"sqlite:///{db_path}", admin_username="", admin_password="")

    with pytest.raises(RuntimeError, match="ADMIN_USERNAME.*ADMIN_PASSWORD"):
        create_app(settings=settings)


def test_admin_rejects_default_credentials(tmp_path):
    db_path = tmp_path / "admin.sqlite3"
    settings = Settings(database_url=f"sqlite:///{db_path}", admin_username="admin", admin_password="admin")

    with pytest.raises(RuntimeError, match="ADMIN_USERNAME.*ADMIN_PASSWORD"):
        create_app(settings=settings)


def test_admin_requires_basic_auth(tmp_path):
    client, _repo = _app(tmp_path)

    response = client.get("/")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


def test_admin_rate_limits_failed_basic_auth_by_ip(tmp_path):
    client, _repo = _app(tmp_path)

    for _ in range(10):
        assert client.get("/", headers=_auth(password="wrong")).status_code == 401
    blocked = client.get("/", headers=_auth(password="wrong"))

    assert blocked.status_code == 429


def test_admin_adds_security_headers(tmp_path):
    client, _repo = _app(tmp_path)

    response = client.get("/", headers=_post_headers())

    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_admin_serves_static_assets_and_uses_file_templates(tmp_path):
    client, _repo = _app(tmp_path)

    response = client.get("/", headers=_post_headers())
    css = client.get("/static/style.css", headers=_post_headers())

    assert response.status_code == 200
    assert "pico.min.css" in response.text
    assert "/static/style.css" in response.text
    assert css.status_code == 200
    assert "message-bubble" in css.text


def test_admin_dialogue_list_filters_searches_and_hides_telegram_ids_from_urls(tmp_path):
    client, repo = _app(tmp_path)
    paused = repo.upsert_client(telegram_id=111, username="paused_user")
    active = repo.upsert_client(telegram_id=222, username="active_user")
    repo.add_message(client_id=paused.id, direction="in", text="нужен букет")
    repo.add_message(client_id=active.id, direction="in", text="привет")
    repo.pause_client(client_id=paused.id, paused_by="manual", reason="manual")

    response = client.get("/?filter=paused&q=paused", headers=_post_headers())

    assert response.status_code == 200
    assert "paused_user" in response.text
    assert "active_user" not in response.text
    assert f"/clients/{paused.id}" in response.text
    assert "/clients/111" not in response.text
    assert "badge danger" in response.text


def test_admin_dialogue_detail_shows_chat_messages_card_and_pause_actions(tmp_path):
    client, repo = _app(tmp_path)
    record = repo.upsert_client(telegram_id=111, username="user1")
    order = repo.get_or_create_active_order(client_id=record.id)
    repo.update_order_card(order_id=order.id, card=OrderCard(budget=5000, colors=["белые"], fulfillment_type="pickup"))
    repo.add_message(client_id=record.id, direction="in", text="хочу букет")
    repo.add_message(client_id=record.id, direction="out", text="Подскажите бюджет")

    response = client.get(f"/clients/{record.id}", headers=_post_headers())

    assert response.status_code == 200
    assert "message-bubble incoming" in response.text
    assert "message-bubble outgoing" in response.text
    assert "хочу букет" in response.text
    assert "Подскажите бюджет" in response.text
    assert "5000" in response.text
    assert "Перехватить" in response.text
    assert "telegram_id=111" not in response.text


def test_admin_pause_resume_and_card_edit_write_events(tmp_path):
    client, repo = _app(tmp_path)
    record = repo.upsert_client(telegram_id=111, username="user1")
    order = repo.get_or_create_active_order(client_id=record.id)

    pause = client.post(f"/clients/{record.id}/pause", headers=_post_headers(), follow_redirects=False)
    assert pause.status_code == 303
    assert repo.get_client_by_id(record.id).bot_paused_at is not None

    resume = client.post(f"/clients/{record.id}/resume", headers=_post_headers(), follow_redirects=False)
    assert resume.status_code == 303
    assert repo.get_client_by_id(record.id).bot_paused_at is None

    edit = client.post(
        f"/clients/{record.id}/card",
        headers=_post_headers(),
        data={
            "budget": "7000",
            "fulfillment_type": "delivery",
            "colors": "белые, розовые",
            "sender_name": "Даня",
            "sender_phone": "89990000001",
            "recipient_name": "Оля",
            "recipient_phone": "89990000002",
            "postcard_text": "люблю",
            "payment_method": "СБП",
        },
        follow_redirects=False,
    )
    assert edit.status_code == 303
    saved = repo.get_order_by_id(order.id).card
    assert saved.budget == 7000
    assert saved.fulfillment_type == "delivery"
    assert saved.colors == ["белые", "розовые"]
    assert saved.sender_name == "Даня"
    assert saved.sender_phone == "89990000001"
    assert saved.recipient_name == "Оля"
    assert saved.recipient_phone == "89990000002"
    assert saved.postcard_text == "люблю"
    assert saved.payment_method == "СБП"
    event = repo.list_events(client_id=record.id, event=EventName.CARD_EDITED_MANUALLY)[0]
    assert "budget" in event.payload_json
    assert "7000" not in event.payload_json


def test_admin_card_edit_can_clear_existing_fields(tmp_path):
    client, repo = _app(tmp_path)
    record = repo.upsert_client(telegram_id=111, username="user1")
    order = repo.get_or_create_active_order(client_id=record.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard(
            budget=7000,
            colors=["белые"],
            sender_name="Даня",
            sender_phone="89990000001",
            recipient_name="Оля",
            recipient_phone="89990000002",
            postcard_text="люблю",
            payment_method="СБП",
        ),
    )

    response = client.post(
        f"/clients/{record.id}/card",
        headers=_post_headers(),
        data={"budget": "", "colors": "", "sender_name": "", "sender_phone": "", "recipient_name": "", "recipient_phone": "", "postcard_text": "", "payment_method": ""},
        follow_redirects=False,
    )

    assert response.status_code == 303
    saved = repo.get_order_by_id(order.id).card
    assert saved.budget is None
    assert saved.colors == []
    assert saved.sender_name is None
    assert saved.sender_phone is None
    assert saved.recipient_name is None
    assert saved.recipient_phone is None
    assert saved.postcard_text is None
    assert saved.payment_method is None


def test_admin_metrics_page_shows_human_readable_sections_for_selected_period(tmp_path):
    client, repo = _app(tmp_path)
    record = repo.upsert_client(telegram_id=111, username=None)
    repo.record_event(client_id=record.id, order_id=None, event=EventName.DIALOG_STARTED)
    repo.record_event(client_id=record.id, order_id=None, event=EventName.ADMIN_REQUEST_SENT)

    response = client.get("/metrics?days=30", headers=_post_headers())

    assert response.status_code == 200
    assert "Воронка" in response.text
    assert "Конверсия в заявку" in response.text
    assert "Доля эскалаций" in response.text
    assert "Медианное время ответа" in response.text
    assert "Обращения вне рабочих часов" in response.text
    assert "30 дней" in response.text


def test_admin_metrics_csv_exports_raw_numbers(tmp_path):
    client, repo = _app(tmp_path)
    record = repo.upsert_client(telegram_id=111, username=None)
    repo.record_event(client_id=record.id, order_id=None, event=EventName.DIALOG_STARTED)

    response = client.get("/metrics.csv?days=7", headers=_post_headers())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "section,metric,value" in response.text
    assert "conversion,dialogs,1" in response.text
