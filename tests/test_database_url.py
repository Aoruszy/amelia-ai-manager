from pathlib import Path

from amelia_manager.db.repository import path_from_sqlite_url


def test_path_from_sqlite_url_relative():
    assert path_from_sqlite_url("sqlite:///data/app.sqlite3") == Path("data/app.sqlite3")


def test_path_from_sqlite_url_plain_path():
    assert path_from_sqlite_url("/tmp/app.sqlite3") == Path("/tmp/app.sqlite3")
