from amelia_manager.db.repository import SQLiteRepository


def _index_names(repo: SQLiteRepository) -> set[str]:
    with repo._connect() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {row["name"] for row in rows}


def test_repository_creates_client_and_persists_messages(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()

    client = repo.upsert_client(telegram_id=123, username="client_user")
    repo.add_message(client_id=client.id, direction="in", text="Здравствуйте")
    repo.add_message(client_id=client.id, direction="out", text="Здравствуйте 🙂")

    loaded = repo.get_client_by_telegram_id(123)
    messages = repo.list_messages(client_id=client.id)

    assert loaded is not None
    assert loaded.telegram_id == 123
    assert loaded.username == "client_user"
    assert [m.direction for m in messages] == ["in", "out"]
    assert [m.text for m in messages] == ["Здравствуйте", "Здравствуйте 🙂"]


def test_repository_updates_client_username_without_duplicate(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()

    first = repo.upsert_client(telegram_id=123, username=None)
    second = repo.upsert_client(telegram_id=123, username="new_name")

    assert first.id == second.id
    assert repo.get_client_by_telegram_id(123).username == "new_name"


def test_repository_stores_conversation_state(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client_user")

    repo.update_client_state(client_id=client.id, stage="bouquet_selection", summary="Хочет букет девушке")

    loaded = repo.get_client_by_telegram_id(123)
    assert loaded.stage == "bouquet_selection"
    assert loaded.summary == "Хочет букет девушке"


def test_repository_list_messages_returns_latest_messages_in_chronological_order(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client_user")

    for index in range(1, 16):
        repo.add_message(client_id=client.id, direction="in", text=f"message {index}")

    messages = repo.list_messages(client_id=client.id, limit=5)

    assert [message.text for message in messages] == [
        "message 11",
        "message 12",
        "message 13",
        "message 14",
        "message 15",
    ]


def test_repository_initializes_hot_path_indexes(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()

    assert {"idx_messages_client_id", "idx_orders_client_status"} <= _index_names(repo)
