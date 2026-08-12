from datetime import date, datetime, timedelta

from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.events import EventName
from amelia_manager.stats_report import format_stats_report, parse_stats_days


def test_stats_report_uses_plain_language_and_previous_period(tmp_path):
    repo = SQLiteRepository(tmp_path / "db.sqlite3")
    repo.initialize()
    today = date(2026, 8, 14)
    start = datetime(2026, 8, 8, 10, 0, 0)
    clients = [repo.upsert_client(telegram_id=i, username=None) for i in range(1, 4)]
    for client in clients:
        repo.record_event(client_id=client.id, order_id=client.id, event=EventName.DIALOG_STARTED, payload={}, created_at=start)
    repo.record_event(client_id=clients[0].id, order_id=1, event=EventName.ADMIN_REQUEST_SENT, payload={}, created_at=start)
    repo.record_event(client_id=clients[1].id, order_id=2, event=EventName.STEP_COMPLETED, payload={"field_code": "budget"}, created_at=start)
    repo.record_event(client_id=clients[2].id, order_id=3, event=EventName.ESCALATED, payload={"risk_category": "guarantee_request"}, created_at=start)
    prev_client = repo.upsert_client(telegram_id=99, username=None)
    repo.record_event(client_id=prev_client.id, order_id=99, event=EventName.DIALOG_STARTED, payload={}, created_at=start - timedelta(days=7))

    report = format_stats_report(repo, days=7, today=today)

    assert "из 3 обращений 1 дошло до заявки" in report
    assert "Эскалации: 33%" in report
    assert "budget" in report
    assert "pass_rate" not in report


def test_parse_stats_days_clamps_bad_values():
    assert parse_stats_days("/stats") == 7
    assert parse_stats_days("/stats 30") == 30
    assert parse_stats_days("/stats nope") == 7
    assert parse_stats_days("/stats 999") == 90
