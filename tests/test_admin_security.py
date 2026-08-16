from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from amelia_manager.admin import create_app
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite:///{tmp_path / 'admin.sqlite3'}",
        "admin_username": "owner",
        "admin_password": "secret-password",
    }
    values.update(overrides)
    return Settings(**values)


def _client(tmp_path: Path, **overrides) -> tuple[TestClient, SQLiteRepository]:
    settings = _settings(tmp_path, **overrides)
    repo = SQLiteRepository(tmp_path / "admin.sqlite3")
    repo.initialize()
    return TestClient(create_app(settings=settings), base_url="https://admin.test"), repo


def test_admin_post_rejects_cross_origin_and_missing_origin_or_referer(tmp_path):
    client, _repo = _client(tmp_path)

    missing = client.post("/catalog/items", data={"name": "Пионы"}, auth=("owner", "secret-password"), follow_redirects=False)
    cross = client.post(
        "/catalog/items",
        data={"name": "Пионы"},
        headers={"Origin": "https://evil.test"},
        auth=("owner", "secret-password"),
        follow_redirects=False,
    )

    assert missing.status_code == 403
    assert cross.status_code == 403


def test_admin_post_allows_same_origin_and_get_is_not_csrf_checked(tmp_path):
    client, repo = _client(tmp_path)

    page = client.get("/catalog", auth=("owner", "secret-password"))
    created = client.post(
        "/catalog/items",
        data={"name": "Пионы"},
        headers={"Origin": "https://admin.test"},
        auth=("owner", "secret-password"),
        follow_redirects=False,
    )

    assert page.status_code == 200
    assert created.status_code == 303
    assert repo.list_catalog_items()[0].name == "Пионы"


def test_admin_ignores_x_forwarded_for_without_trusted_proxy(tmp_path):
    client, _repo = _client(tmp_path, admin_trusted_proxy_ips="")

    for i in range(10):
        response = client.get("/", headers={"X-Forwarded-For": f"198.51.100.{i}"}, auth=("owner", "wrong"))
        assert response.status_code == 401
    blocked = client.get("/", headers={"X-Forwarded-For": "198.51.100.200"}, auth=("owner", "wrong"))

    assert blocked.status_code == 429


def test_admin_uses_x_forwarded_for_from_trusted_proxy(tmp_path):
    client, _repo = _client(tmp_path, admin_trusted_proxy_ips="testclient")

    for _ in range(10):
        response = client.get("/", headers={"X-Forwarded-For": "198.51.100.10"}, auth=("owner", "wrong"))
        assert response.status_code == 401
    blocked = client.get("/", headers={"X-Forwarded-For": "198.51.100.10"}, auth=("owner", "wrong"))
    other = client.get("/", headers={"X-Forwarded-For": "198.51.100.11"}, auth=("owner", "wrong"))

    assert blocked.status_code == 429
    assert other.status_code == 401
