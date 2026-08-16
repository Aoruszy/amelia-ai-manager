from datetime import date

from fastapi.testclient import TestClient

from amelia_manager.admin import create_app
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.events import EventName
from amelia_manager.stock import StockStatus
from amelia_manager.stock_source import DbCatalogStockSource
from amelia_manager.telegram_runtime import handle_stock_command


def _settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'admin.sqlite3'}",
        admin_username="owner",
        admin_password="secret-password",
        auto_reply_enabled=False,
    )


def test_stock_command_updates_catalog_and_bot_reads_it_immediately(tmp_path):
    repo = SQLiteRepository(tmp_path / "stock.sqlite3")
    repo.initialize()

    handle_stock_command(repo, sender_id=99, text="/stock\nпионы — 5", today=date(2026, 8, 13))
    assert DbCatalogStockSource(repo).fetch().items[0].quantity_number == 5

    handle_stock_command(repo, sender_id=99, text="/stock\nпионы — нет", today=date(2026, 8, 13))
    item = DbCatalogStockSource(repo).fetch().items[0]
    assert item.status == StockStatus.UNAVAILABLE
    assert item.quantity_number == 0


def test_admin_catalog_requires_auth_and_allows_mobile_quick_sold_out(tmp_path):
    settings = _settings(tmp_path)
    repo = SQLiteRepository(tmp_path / "admin.sqlite3")
    repo.initialize()
    item = repo.upsert_catalog_item(name="Пионы", quantity_number=4, price=4500, unit="шт", updated_by=0)
    client = TestClient(create_app(settings=settings))

    assert client.get("/catalog").status_code == 401
    page = client.get("/catalog", auth=("owner", "secret-password"))
    assert page.status_code == 200
    assert "Пионы" in page.text
    assert 'inputmode="numeric"' in page.text
    assert "data-catalog-card" in page.text

    response = client.post(f"/catalog/items/{item.id}/quick", json={"action": "sold_out"}, headers={"Origin": "http://testserver"}, auth=("owner", "secret-password"))
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["status"] == "unavailable"
    assert body["item"]["quantity_number"] == 0
    assert DbCatalogStockSource(repo).fetch().items[0].status == StockStatus.UNAVAILABLE
    events = repo.list_events(date_from=date.today(), date_to=date.today())
    catalog_events = [event for event in events if event.event == EventName.CATALOG_UPDATED.value]
    assert catalog_events
    assert "4500" not in catalog_events[-1].payload_json
    assert "quantity_number" in catalog_events[-1].payload_json


def test_admin_catalog_add_and_hide_without_delete(tmp_path):
    settings = _settings(tmp_path)
    repo = SQLiteRepository(tmp_path / "admin.sqlite3")
    repo.initialize()
    client = TestClient(create_app(settings=settings))

    response = client.post(
        "/catalog/items",
        data={"name": "Гортензия", "quantity_number": "2", "price": "1800", "unit": "шт"},
        headers={"Origin": "http://testserver"},
        auth=("owner", "secret-password"),
        follow_redirects=False,
    )
    assert response.status_code == 303
    [item] = repo.list_catalog_items(include_inactive=True)
    assert item.name == "Гортензия"

    response = client.post(f"/catalog/items/{item.id}/hide", headers={"Origin": "http://testserver"}, auth=("owner", "secret-password"), follow_redirects=False)
    assert response.status_code == 303
    assert repo.list_catalog_items() == []
    assert repo.list_catalog_items(include_inactive=True)[0].is_active is False
