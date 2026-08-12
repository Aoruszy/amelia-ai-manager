from datetime import datetime
from zoneinfo import ZoneInfo

from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.telegram_runtime import build_off_hours_reply, should_send_off_hours_reply, is_within_work_hours


def _settings() -> Settings:
    return Settings(
        telegram_api_id=1,
        telegram_api_hash="hash",
        telegram_phone="+100****0000",
        admin_chat_id=123,
        llm_api_key="key",
        work_hours_start="09:00",
        work_hours_end="20:00",
    )


def test_work_hours_detects_inside_and_outside_window():
    settings = _settings()
    tz = ZoneInfo("Europe/Kaliningrad")

    assert is_within_work_hours(datetime(2026, 8, 10, 10, 0, tzinfo=tz), settings=settings) is True
    assert is_within_work_hours(datetime(2026, 8, 10, 3, 0, tzinfo=tz), settings=settings) is False
    assert is_within_work_hours(datetime(2026, 8, 10, 20, 30, tzinfo=tz), settings=settings) is False


def test_off_hours_reply_points_to_opening_time_without_order_promises():
    settings = _settings()
    reply = build_off_hours_reply(settings=settings)

    assert "9:00" in reply or "09:00" in reply
    assert "менеджер" in reply.lower()
    assert "заказ подтверж" not in reply.lower()
    assert "оплату" not in reply.lower()


def test_off_hours_reply_is_sent_once_until_next_work_period(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username=None)
    settings = _settings()
    tz = ZoneInfo("Europe/Kaliningrad")
    now = datetime(2026, 8, 10, 3, 0, tzinfo=tz)

    assert should_send_off_hours_reply(repo, client_id=client.id, now=now, settings=settings) is True

    repo.add_message(client_id=client.id, direction="in", text="Первое ночное")
    repo.add_message(client_id=client.id, direction="out", text=build_off_hours_reply(settings=settings))

    assert should_send_off_hours_reply(repo, client_id=client.id, now=now, settings=settings) is False
    assert [m.direction for m in repo.list_messages(client_id=client.id, limit=10)].count("in") == 1
