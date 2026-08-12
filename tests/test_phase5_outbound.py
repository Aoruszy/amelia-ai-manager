from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from amelia_manager.company_profile import load_company_profile
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.events import EventName
from amelia_manager.order_card import OrderCard
from amelia_manager.outbound import (
    OutboundKind,
    build_outbound_text,
    build_order_status_reply,
    is_opt_out_text,
    is_order_status_question,
    process_outbound_tick,
    schedule_followups_after_reply,
    schedule_order_reminders,
)


class FakeTelegramClient:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text):
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append((chat_id, text))


class BrokenLLM:
    async def generate(self, prompt: str) -> str:
        raise RuntimeError("llm down")


def test_outbound_repository_schedules_due_sends_and_cancels(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)
    when = datetime(2026, 8, 14, 10, 0, 0)

    first = repo.schedule_outbound(client_id=client.id, order_id=None, kind=OutboundKind.FOLLOWUP_1, scheduled_at=when)
    duplicate = repo.schedule_outbound(client_id=client.id, order_id=None, kind=OutboundKind.FOLLOWUP_1, scheduled_at=when + timedelta(hours=1))

    assert first.id == duplicate.id
    assert repo.list_due_outbound(now=when)[0].kind == OutboundKind.FOLLOWUP_1
    repo.mark_outbound_sent(first.id, sent_at=when)
    assert repo.list_due_outbound(now=when) == []

    second = repo.schedule_outbound(client_id=client.id, order_id=None, kind=OutboundKind.FOLLOWUP_2, scheduled_at=when)
    cancelled = repo.cancel_pending_followups(client_id=client.id)
    assert cancelled == [second]
    assert repo.list_due_outbound(now=when) == []


def test_opt_out_sets_client_flag_and_prevents_future_initiative(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)

    assert is_opt_out_text("Не пишите мне больше") is True
    repo.mark_client_opted_out(client_id=client.id)

    refreshed = repo.get_client_by_telegram_id(10)
    assert refreshed.opted_out_at is not None


def test_status_question_answers_from_active_order_card(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard(fulfillment_type="delivery", delivery_date="2026-08-15", delivery_time="15:00", admin_request_sent=True),
    )

    assert is_order_status_question("Что там с моим заказом?") is True
    reply = build_order_status_reply(repo, client_id=client.id, company_profile=load_company_profile("amelia_flowers"))

    assert "2026-08-15" in reply
    assert "15:00" in reply
    assert "доставка" in reply.lower()
    assert "курьер выехал" not in reply.lower()


@pytest.mark.asyncio
async def test_followup_text_falls_back_to_profile_when_llm_fails():
    text = await build_outbound_text(
        OutboundKind.FOLLOWUP_1.value,
        OrderCard(),
        load_company_profile("amelia_flowers"),
        llm_client=BrokenLLM(),
    )

    assert "примерный бюджет" in text.lower()
    assert "можно не отвечать" in text.lower()


def test_followups_schedule_only_after_real_dialogue_and_not_ready_or_escalated(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    now = datetime(2026, 8, 14, 10, 0, 0)

    schedule_followups_after_reply(repo, client=client, order=order, inbound_count=1, action_kind="send", now=now)
    assert repo.list_due_outbound(now=now + timedelta(days=4)) == []

    schedule_followups_after_reply(repo, client=client, order=order, inbound_count=2, action_kind="send", now=now)
    due = repo.list_due_outbound(now=now + timedelta(days=4))
    assert [item.kind for item in due] == [OutboundKind.FOLLOWUP_1, OutboundKind.FOLLOWUP_2]

    repo.cancel_pending_followups(client_id=client.id)
    schedule_followups_after_reply(repo, client=client, order=order, inbound_count=2, action_kind="human_review", now=now)
    assert repo.list_due_outbound(now=now + timedelta(days=4)) == []


def test_followups_do_not_schedule_when_client_opted_out(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)
    repo.mark_client_opted_out(client_id=client.id)
    client = repo.get_client_by_id(client.id)
    order = repo.get_or_create_active_order(client_id=client.id)

    schedule_followups_after_reply(repo, client=client, order=order, inbound_count=2, action_kind="send", now=datetime(2026, 8, 14, 10, 0, 0))

    assert repo.list_due_outbound(now=datetime(2026, 8, 18, 10, 0, 0)) == []


def test_followups_do_not_schedule_after_admin_request_sent(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(order_id=order.id, card=OrderCard(admin_request_sent=True))
    order = repo.get_order_by_id(order.id)

    schedule_followups_after_reply(repo, client=client, order=order, inbound_count=2, action_kind="send", now=datetime(2026, 8, 14, 10, 0, 0))

    assert repo.list_due_outbound(now=datetime(2026, 8, 18, 10, 0, 0)) == []


def test_followups_do_not_schedule_when_card_is_ready(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard(
            budget=5000,
            colors=["белые"],
            fulfillment_type="pickup",
            delivery_date="2026-08-15",
            delivery_time="12:00",
            sender_name="Анна",
            sender_phone="+79990000000",
        ),
    )
    order = repo.get_order_by_id(order.id)

    schedule_followups_after_reply(repo, client=client, order=order, inbound_count=2, action_kind="send", now=datetime(2026, 8, 14, 10, 0, 0))

    assert repo.list_due_outbound(now=datetime(2026, 8, 18, 10, 0, 0)) == []


@pytest.mark.asyncio
async def test_scheduler_respects_work_hours_debounce_retries_and_sends(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    due_at = datetime(2026, 8, 14, 7, 0, 0, tzinfo=ZoneInfo("Europe/Kaliningrad"))
    scheduled = repo.schedule_outbound(client_id=client.id, order_id=order.id, kind=OutboundKind.FOLLOWUP_1, scheduled_at=due_at)
    settings = Settings(work_hours_start="09:00", work_hours_end="20:00")

    client_api = FakeTelegramClient()
    await process_outbound_tick(client_api, repo=repo, settings=settings, company_profile=load_company_profile("amelia_flowers"), now=due_at, active_buffers=set())
    assert client_api.sent == []
    assert repo.list_due_outbound(now=due_at + timedelta(minutes=30)) == []

    work_time = datetime(2026, 8, 14, 9, 0, 0, tzinfo=ZoneInfo("Europe/Kaliningrad"))
    await process_outbound_tick(client_api, repo=repo, settings=settings, company_profile=load_company_profile("amelia_flowers"), now=work_time, active_buffers={client.id})
    assert client_api.sent == []
    assert repo.get_outbound(scheduled.id).sent_at is None

    await process_outbound_tick(client_api, repo=repo, settings=settings, company_profile=load_company_profile("amelia_flowers"), now=work_time, active_buffers=set())
    assert client_api.sent and "можно не отвечать" in client_api.sent[0][1].lower()
    assert repo.get_outbound(scheduled.id).sent_at is not None


@pytest.mark.asyncio
async def test_failed_outbound_retries_then_cancels_after_three_attempts(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    now = datetime(2026, 8, 14, 10, 0, 0, tzinfo=ZoneInfo("Europe/Kaliningrad"))
    scheduled = repo.schedule_outbound(client_id=client.id, order_id=order.id, kind=OutboundKind.FOLLOWUP_1, scheduled_at=now)
    settings = Settings(work_hours_start="09:00", work_hours_end="20:00")

    for _ in range(3):
        await process_outbound_tick(FakeTelegramClient(fail=True), repo=repo, settings=settings, company_profile=load_company_profile("amelia_flowers"), now=now, active_buffers=set())

    record = repo.get_outbound(scheduled.id)
    assert record.attempt_count == 3
    assert record.cancelled_at is not None


def test_order_reminder_scheduled_once_for_admin_sent_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard(fulfillment_type="pickup", delivery_date="2026-08-15", delivery_time="12:00", admin_request_sent=True),
    )

    count = schedule_order_reminders(repo, now=datetime(2026, 8, 14, 10, 0, 0), company_profile=load_company_profile("amelia_flowers"))
    second = schedule_order_reminders(repo, now=datetime(2026, 8, 14, 11, 0, 0), company_profile=load_company_profile("amelia_flowers"))

    assert count == 1
    assert second == 0
    assert repo.list_due_outbound(now=datetime(2026, 8, 14, 10, 0, 0))[0].kind == OutboundKind.ORDER_REMINDER


def test_order_reminder_is_not_rescheduled_after_it_was_sent(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(order_id=order.id, card=OrderCard(fulfillment_type="pickup", delivery_date="2026-08-15", admin_request_sent=True))

    schedule_order_reminders(repo, now=datetime(2026, 8, 14, 10, 0, 0), company_profile=load_company_profile("amelia_flowers"))
    reminder = repo.list_due_outbound(now=datetime(2026, 8, 14, 10, 0, 0))[0]
    repo.mark_outbound_sent(reminder.id, sent_at=datetime(2026, 8, 14, 10, 1, 0))

    assert schedule_order_reminders(repo, now=datetime(2026, 8, 14, 11, 0, 0), company_profile=load_company_profile("amelia_flowers")) == 0


def test_followups_are_never_scheduled_more_than_two_per_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=10, username=None)
    order = repo.get_or_create_active_order(client_id=client.id)
    now = datetime(2026, 8, 14, 10, 0, 0)

    schedule_followups_after_reply(repo, client=client, order=order, inbound_count=2, action_kind="send", now=now)
    for item in repo.list_due_outbound(now=now + timedelta(days=4)):
        repo.mark_outbound_sent(item.id, sent_at=now + timedelta(days=4))
    schedule_followups_after_reply(repo, client=client, order=order, inbound_count=3, action_kind="send", now=now + timedelta(days=5))

    assert repo.list_due_outbound(now=now + timedelta(days=10)) == []
