from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import pytest

from amelia_manager.config import Settings
from amelia_manager.telegram_runtime import retention_cleanup_loop, track_background_task, weekly_stats_loop


class _FakeRepo:
    def __init__(self):
        self.cleanup_calls: list[tuple[int, int]] = []

    def cleanup_pii_older_than(self, *, retention_days: int, event_retention_days: int):
        self.cleanup_calls.append((retention_days, event_retention_days))

        class Result:
            deleted_messages = 0
            anonymized_orders = 0
            deleted_events = 0

        return Result()


def test_settings_expose_retention_cleanup_intervals():
    settings = Settings(retention_cleanup_interval_hours=12, event_retention_days=120)

    assert settings.retention_cleanup_interval_hours == 12
    assert settings.event_retention_days == 120


@pytest.mark.asyncio
async def test_retention_cleanup_loop_uses_settings_and_continues_after_sleep():
    repo = _FakeRepo()
    settings = Settings(pii_retention_days=30, event_retention_days=120, retention_cleanup_interval_hours=24)
    sleeps: list[int] = []

    async def sleep(seconds: int):
        sleeps.append(seconds)
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await retention_cleanup_loop(repo=repo, settings=settings, sleep=sleep)

    assert repo.cleanup_calls == [(30, 120)]
    assert sleeps == [24 * 60 * 60]


@pytest.mark.asyncio
async def test_weekly_stats_loop_survives_send_message_exception(monkeypatch):
    import amelia_manager.telegram_runtime as runtime

    class MondayDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 17, 10, 0, tzinfo=tz)

    class FailingOnceTelegram:
        def __init__(self):
            self.calls = 0

        async def send_message(self, chat_id, text):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("telegram down")

    sleeps = 0

    async def sleep(_seconds: int):
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 2:
            raise asyncio.CancelledError

    telegram = FailingOnceTelegram()
    monkeypatch.setattr(runtime, "datetime", MondayDatetime)
    monkeypatch.setattr(runtime, "format_stats_report", lambda *args, **kwargs: "stats")

    with pytest.raises(asyncio.CancelledError):
        await weekly_stats_loop(
            telegram,
            repo=object(),
            admin_chat_id=123,
            settings=Settings(work_hours_start="09:00", work_hours_end="20:00"),
            timezone_name="UTC",
            sleep=sleep,
        )

    assert telegram.calls == 2


def test_track_background_task_logs_unexpected_completion(caplog):
    async def boom():
        raise RuntimeError("background died")

    tasks: set[asyncio.Task] = set()
    caplog.set_level(logging.ERROR)

    async def run_task():
        task = asyncio.create_task(boom())
        track_background_task(task, tasks, name="boom-loop")
        await asyncio.sleep(0)

    asyncio.run(run_task())

    assert tasks == set()
    assert "background_task_failed" in caplog.text
    assert "boom-loop" in caplog.text
