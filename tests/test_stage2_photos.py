from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amelia_manager.admin import create_app
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.media_storage import store_image_bytes
from amelia_manager.stock import BudgetOption, BudgetOptions, StockItem, StockStatus, select_budget_options
from amelia_manager.telegram_runtime import send_budget_options_album

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 32


def _auth(username: str = "admin", password: str = "secret") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _post_headers() -> dict[str, str]:
    return {**_auth(), "Origin": "http://testserver"}


def _app(tmp_path: Path, *, max_bytes: int = 5 * 1024 * 1024) -> tuple[TestClient, SQLiteRepository, Path]:
    db_path = tmp_path / "admin.sqlite3"
    repo = SQLiteRepository(db_path)
    repo.initialize()
    settings = Settings(
        database_url=f"sqlite:///{db_path}",
        admin_username="admin",
        admin_password="secret",
        catalog_image_max_bytes=max_bytes,
    )
    return TestClient(create_app(settings=settings)), repo, db_path.parent / settings.media_storage_dir


class FakeTelegramClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.files: list[tuple[int, list[Path], str]] = []

    async def send_file(self, sender_id: int, files: list[Path], *, caption: str) -> None:
        if self.fail:
            raise RuntimeError("telegram failed")
        self.files.append((sender_id, list(files), caption))


def test_catalog_item_photo_upload_validates_type_size_and_generates_name(tmp_path):
    client, repo, media_root = _app(tmp_path, max_bytes=64)
    item = repo.upsert_catalog_item(name="Букет нежный", quantity_number=3, price=5000, unit="букет")

    bad_type = client.post(
        f"/catalog/items/{item.id}/photo",
        headers=_post_headers(),
        files={"photo": ("../../hack.gif", b"GIF89a", "image/gif")},
    )
    assert bad_type.status_code == 400
    assert "JPEG" in bad_type.text

    too_large = client.post(
        f"/catalog/items/{item.id}/photo",
        headers=_post_headers(),
        files={"photo": ("big.png", b"\x89PNG\r\n\x1a\n" + b"x" * 128, "image/png")},
    )
    assert too_large.status_code == 400
    assert "слишком большой" in too_large.text

    ok = client.post(
        f"/catalog/items/{item.id}/photo",
        headers=_post_headers(),
        files={"photo": ("../../original.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    updated = repo.get_catalog_item(item.id)
    assert updated is not None
    assert updated.image_path is not None
    assert updated.image_path.startswith("catalog/")
    assert "original" not in updated.image_path
    assert ".." not in updated.image_path
    assert (media_root / updated.image_path).exists()


def test_catalog_media_route_requires_auth(tmp_path):
    client, repo, media_root = _app(tmp_path)
    stored = store_image_bytes(PNG_BYTES, media_root=media_root, namespace="catalog", max_bytes=1024)
    item = repo.upsert_catalog_item(name="Букет с фото", quantity_number=3, price=5000, unit="букет")
    repo.update_catalog_item(item.id, image_path=stored.relative_path)

    assert client.get(f"/catalog/media/{stored.relative_path}").status_code == 401
    response = client.get(f"/catalog/media/{stored.relative_path}", headers=_auth())
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_budget_options_with_three_photos_send_one_album_with_caption(tmp_path):
    paths = []
    for index in range(3):
        stored = store_image_bytes(PNG_BYTES, media_root=tmp_path, namespace="catalog", max_bytes=1024)
        paths.append(stored.relative_path)
    options = BudgetOptions([
        BudgetOption("Букет 1", 3000, "букет", paths[0]),
        BudgetOption("Букет 2", 5000, "букет", paths[1]),
        BudgetOption("Букет 3", 7000, "букет", paths[2]),
    ])
    client = FakeTelegramClient()

    sent = await send_budget_options_album(client, sender_id=42, budget_options=options, media_root=tmp_path, caption="Могу показать три варианта")

    assert sent is True
    assert len(client.files) == 1
    assert len(client.files[0][1]) == 3
    assert client.files[0][2] == "Могу показать три варианта"


@pytest.mark.asyncio
async def test_budget_options_with_one_photo_or_send_failure_falls_back_to_text(tmp_path):
    stored = store_image_bytes(PNG_BYTES, media_root=tmp_path, namespace="catalog", max_bytes=1024)
    one_photo = BudgetOptions([
        BudgetOption("Букет 1", 3000, "букет", stored.relative_path),
        BudgetOption("Букет 2", 5000, "букет", None),
        BudgetOption("Букет 3", 7000, "букет", None),
    ])
    assert await send_budget_options_album(FakeTelegramClient(), sender_id=42, budget_options=one_photo, media_root=tmp_path, caption="x") is False

    all_photos = BudgetOptions([BudgetOption(f"Букет {i}", i * 1000, "букет", stored.relative_path) for i in range(1, 4)])
    assert await send_budget_options_album(FakeTelegramClient(fail=True), sender_id=42, budget_options=all_photos, media_root=tmp_path, caption="x") is False


def test_budget_selection_excludes_inactive_zero_and_forbidden_sensitive_items():
    items = [
        StockItem("Букет светлый", StockStatus.AVAILABLE, "3", 3, 3000, "букет", "catalog/1.png"),
        StockItem("Букет траурный", StockStatus.AVAILABLE, "3", 3, 5000, "букет", "catalog/2.png"),
        StockItem("Букет ноль", StockStatus.AVAILABLE, "0", 0, 7000, "букет", "catalog/3.png"),
        StockItem("Роза", StockStatus.AVAILABLE, "3", 3, 1000, "шт", "catalog/4.png"),
        StockItem("Неактивный", StockStatus.UNAVAILABLE, "нет", 0, 9000, "букет", "catalog/5.png"),
    ]

    regular = select_budget_options(items, desired_text="не знаю", composition_units=("букет",))
    assert [item.name for item in regular.items] == ["Букет светлый", "Букет траурный"]

    sensitive = select_budget_options(
        items,
        desired_text="не знаю",
        composition_units=("букет",),
        sensitive_occasion=True,
        sensitive_forbidden_words=("траур",),
    )
    assert [item.name for item in sensitive.items] == ["Букет светлый", "Букет траурный"]
    assert sensitive.hide_names is True
