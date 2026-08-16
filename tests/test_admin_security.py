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

    assert blocked.status_code == 429

    for _ in range(10):
        response = client.get("/", headers={"X-Forwarded-For": "198.51.100.11"}, auth=("owner", "wrong"))
        assert response.status_code == 401
    other_blocked = client.get("/", headers={"X-Forwarded-For": "198.51.100.11"}, auth=("owner", "wrong"))

    assert other_blocked.status_code == 429


def test_admin_rate_limit_cannot_be_bypassed_by_spoofed_left_xff_chain(tmp_path):
    client, _repo = _client(tmp_path, admin_trusted_proxy_ips="testclient")

    for i in range(10):
        response = client.get(
            "/",
            headers={"X-Forwarded-For": f"203.0.113.{i}, 198.51.100.10"},
            auth=("owner", "wrong"),
        )
        assert response.status_code == 401
    blocked = client.get(
        "/",
        headers={"X-Forwarded-For": "203.0.113.250, 198.51.100.10"},
        auth=("owner", "wrong"),
    )

    assert blocked.status_code == 429


def test_admin_uses_first_untrusted_address_from_right_of_xff_chain(tmp_path):
    client, _repo = _client(
        tmp_path,
        admin_trusted_proxy_ips="testclient,203.0.113.5,203.0.113.6",
    )

    for i in range(10):
        response = client.get(
            "/",
            headers={"X-Forwarded-For": f"192.0.2.{i}, 198.51.100.20, 203.0.113.5, 203.0.113.6"},
            auth=("owner", "wrong"),
        )
        assert response.status_code == 401
    blocked = client.get(
        "/",
        headers={"X-Forwarded-For": "192.0.2.250, 198.51.100.20, 203.0.113.5, 203.0.113.6"},
        auth=("owner", "wrong"),
    )

    assert blocked.status_code == 429


def test_admin_falls_back_to_peer_when_all_xff_addresses_are_trusted(tmp_path):
    client, _repo = _client(
        tmp_path,
        admin_trusted_proxy_ips="testclient,203.0.113.5,203.0.113.6",
    )

    for i in range(10):
        response = client.get(
            "/",
            headers={"X-Forwarded-For": f"203.0.113.5, 203.0.113.6, 203.0.113.{5 + i % 2}"},
            auth=("owner", "wrong"),
        )
        assert response.status_code == 401
    blocked = client.get(
        "/",
        headers={"X-Forwarded-For": "203.0.113.6, 203.0.113.5"},
        auth=("owner", "wrong"),
    )

    assert blocked.status_code == 429
