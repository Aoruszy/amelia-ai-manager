from datetime import datetime, timedelta

from amelia_manager.db.repository import SQLiteRepository


def test_list_messages_can_filter_latest_messages_by_age_window(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client_user")

    old = repo.add_message(client_id=client.id, direction="in", text="старое сообщение")
    with repo._connect() as conn:
        conn.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ((datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"), old.id),
        )

    for index in range(1, 13):
        repo.add_message(client_id=client.id, direction="in", text=f"свежее {index}")

    messages = repo.list_messages(client_id=client.id, limit=10, since_days=7)

    assert [message.text for message in messages] == [f"свежее {index}" for index in range(3, 13)]
    assert "старое сообщение" not in [message.text for message in messages]


def test_list_messages_without_age_filter_keeps_existing_behavior(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client_user")

    old = repo.add_message(client_id=client.id, direction="in", text="старое сообщение")
    with repo._connect() as conn:
        conn.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ((datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"), old.id),
        )
    repo.add_message(client_id=client.id, direction="in", text="свежее сообщение")

    messages = repo.list_messages(client_id=client.id, limit=10)

    assert [message.text for message in messages] == ["старое сообщение", "свежее сообщение"]


def _msg(created_at: str, direction: str, text: str):
    from types import SimpleNamespace

    return SimpleNamespace(created_at=created_at, direction=direction, text=text)


def test_history_is_cut_at_the_last_long_pause():
    """Вчерашний заказ не должен попадать в промпт сегодняшнего разговора."""
    from amelia_manager.telegram_runtime import messages_after_last_session_gap

    history = [
        _msg("2026-08-18 16:52", "in", "нужен букет из голубой гортензии, бюджет 7000"),
        _msg("2026-08-18 17:01", "out", "Итог заказа: ..."),
        _msg("2026-08-19 12:10", "in", "Здравствуйте"),
        _msg("2026-08-19 12:10", "out", "Здравствуйте 🙂 Чем могу помочь?"),
        _msg("2026-08-19 12:10", "in", "букет до 5000, самовывоз"),
    ]

    kept = messages_after_last_session_gap(history, gap_hours=6)

    assert [message.text for message in kept] == [
        "Здравствуйте",
        "Здравствуйте 🙂 Чем могу помочь?",
        "букет до 5000, самовывоз",
    ]


def test_a_single_sitting_is_never_cut():
    """Негативный случай: внутри одного разговора переписку резать нельзя."""
    from amelia_manager.telegram_runtime import messages_after_last_session_gap

    history = [
        _msg("2026-08-19 10:00", "in", "нужен букет"),
        _msg("2026-08-19 10:01", "out", "На какой бюджет?"),
        _msg("2026-08-19 12:05", "in", "5000"),
        _msg("2026-08-19 12:40", "out", "Оттенки?"),
    ]

    assert messages_after_last_session_gap(history, gap_hours=6) == history


def test_broken_timestamps_do_not_drop_history():
    from amelia_manager.telegram_runtime import messages_after_last_session_gap

    history = [_msg("не дата", "in", "первое"), _msg("тоже не дата", "in", "второе")]

    assert messages_after_last_session_gap(history, gap_hours=6) == history
