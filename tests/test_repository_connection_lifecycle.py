from amelia_manager.db.repository import SQLiteRepository


def test_repository_closes_sqlite_connections(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()

    conn_cm = repo._connect()
    with conn_cm as conn:
        conn.execute("SELECT 1").fetchone()

    try:
        conn.execute("SELECT 1").fetchone()
    except Exception as exc:
        assert "closed" in str(exc).lower()
    else:
        raise AssertionError("sqlite connection was not closed after repository context")
