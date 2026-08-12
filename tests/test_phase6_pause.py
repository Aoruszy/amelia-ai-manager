from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from amelia_manager.company_profile import load_company_profile
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.events import EventName
from amelia_manager.outbound import OutboundKind, process_outbound_tick, schedule_followups_after_reply
from amelia_manager.telegram_runtime import handle_admin_control_command


class FakeTelegramClient:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


def test_pause_resume_repository_state_and_events(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=111, username="user1")
    paused_at = datetime(2026, 8, 15, 10, 0, 0)

    repo.pause_client(client_id=client.id, paused_by="manual", reason="manual", paused_at=paused_at)

    paused = repo.get_client_by_id(client.id)
    assert paused.bot_paused_at == "2026-08-15 10:00:00"
    assert paused.paused_by == "manual"
    assert repo.list_paused_clients()[0].telegram_id == 111
    assert repo.list_events(client_id=client.id, event=EventName.BOT_PAUSED)[0].payload_json == '{"reason": "manual"}'

    repo.resume_client(client_id=client.id, reason="manual", resumed_at=paused_at)

    resumed = repo.get_client_by_id(client.id)
    assert resumed.bot_paused_at is None
    assert resumed.paused_by is None
    assert repo.list_paused_clients() == []
    assert repo.list_events(client_id=client.id, event=EventName.BOT_RESUMED)[0].payload_json == '{"reason": "manual"}'


@pytest.mark.asyncio
async def test_paused_client_does_not_receive_outbound(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=111, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    now = datetime(2026, 8, 15, 10, 0, 0, tzinfo=ZoneInfo("Europe/Kaliningrad"))
    repo.pause_client(client_id=client.id, paused_by="manual", reason="manual", paused_at=now)
    repo.schedule_outbound(client_id=client.id, order_id=order.id, kind=OutboundKind.FOLLOWUP_1, scheduled_at=now)

    telegram = FakeTelegramClient()
    await process_outbound_tick(
        telegram,
        repo=repo,
        settings=Settings(work_hours_start="09:00", work_hours_end="20:00"),
        company_profile=load_company_profile("amelia_flowers"),
        now=now,
        active_buffers=set(),
    )

    assert telegram.sent == []
    assert repo.list_due_outbound(now=now)[0].sent_at is None


def test_explicit_pause_blocks_future_followup_scheduling(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=111, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.pause_client(client_id=client.id, paused_by="manual", reason="manual")
    client = repo.get_client_by_id(client.id)

    scheduled = schedule_followups_after_reply(
        repo,
        client=client,
        order=order,
        inbound_count=2,
        action_kind="send",
        now=datetime(2026, 8, 15, 10, 0, 0),
    )

    assert scheduled == 0
    assert repo.list_due_outbound(now=datetime(2026, 8, 20, 10, 0, 0)) == []


def test_admin_pause_resume_paused_commands(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    repo.upsert_client(telegram_id=111, username="user1")

    pause_reply = handle_admin_control_command(repo, "/pause 111", admin_id=999)
    assert "пауза" in pause_reply.lower()
    assert repo.get_client_by_telegram_id(111).bot_paused_at is not None

    paused_reply = handle_admin_control_command(repo, "/paused", admin_id=999)
    assert "111" in paused_reply
    assert "user1" in paused_reply

    resume_reply = handle_admin_control_command(repo, "/resume 111", admin_id=999)
    assert "вернул" in resume_reply.lower()
    assert repo.get_client_by_telegram_id(111).bot_paused_at is None
