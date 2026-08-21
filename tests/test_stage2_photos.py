from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from amelia_manager.admin import create_app
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.media_storage import image_data_url_for_llm, store_image_bytes
from amelia_manager.order_card import OrderCard
from amelia_manager.stock import BudgetOption, BudgetOptions, StockItem, StockStatus, select_budget_options
from amelia_manager.telegram_runtime import add_client_photo_to_order, latest_client_photo_data_url, send_admin_order_request_if_ready, send_budget_options_album
from amelia_manager.conversation_engine import ConversationEngine


class StaticLLM:
    async def generate(self, prompt: str) -> str:
        return '{"reply":"ok"}'


class CapturingVisionLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate(self, prompt: str, **kwargs) -> str:
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        return self.response

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 32


def _valid_png_bytes(color: tuple[int, int, int] = (255, 0, 0), *, size: tuple[int, int] = (16, 16)) -> bytes:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))

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


@pytest.mark.asyncio
async def test_client_photo_is_bound_to_order_visible_in_admin_and_sent_to_manager(tmp_path):
    client, repo, media_root = _app(tmp_path)
    person = repo.upsert_client(telegram_id=555, username="photo_user")
    order = repo.get_or_create_active_order(client_id=person.id)
    stored = store_image_bytes(JPEG_BYTES, media_root=media_root, namespace=f"orders/{order.id}", max_bytes=1024)
    card = add_client_photo_to_order(repo, order=order, relative_path=stored.relative_path)
    ready_card = OrderCard.from_dict({
        **card.to_dict(),
        "budget": 5000,
        "colors": ["розы"],
        "fulfillment_type": "delivery",
        "delivery_date": "2026-08-20",
        "delivery_time": "14:00",
        "address": "Гайдара 173",
        "sender_name": "Даня",
        "sender_phone": "89990000001",
        "recipient_name": "Анна",
        "recipient_phone": "89990000002",
        "payment_method": "transfer",
    })
    repo.update_order_card(order_id=order.id, card=ready_card)

    page = client.get(f"/clients/{person.id}", headers=_auth())
    assert page.status_code == 200
    assert "Фото клиента" in page.text
    assert stored.relative_path in page.text

    tg = FakeTelegramClient()
    sent = await send_admin_order_request_if_ready(
        tg,
        repo=repo,
        order=repo.get_order_by_id(order.id),
        admin_chat_id=999,
        client_label="@photo_user / 555",
        media_root=media_root,
    )
    assert sent is True
    assert len(tg.messages) == 1
    assert len(tg.files) == 1
    assert tg.files[0][2] == "Фото клиента к заявке"


def test_retention_cleanup_deletes_client_photo_files(tmp_path):
    _client, repo, media_root = _app(tmp_path)
    person = repo.upsert_client(telegram_id=777, username="old")
    order = repo.get_or_create_active_order(client_id=person.id)
    stored = store_image_bytes(PNG_BYTES, media_root=media_root, namespace=f"orders/{order.id}", max_bytes=1024)
    card = add_client_photo_to_order(repo, order=order, relative_path=stored.relative_path)
    repo.update_order_card(order_id=order.id, card=OrderCard.from_dict({**card.to_dict(), "admin_request_sent": True}))
    with repo._connect() as conn:
        conn.execute("UPDATE orders SET updated_at = '2020-01-01 00:00:00' WHERE id = ?", (order.id,))

    result = repo.cleanup_pii_older_than(retention_days=30, media_root=media_root)

    assert result.anonymized_orders == 1
    assert not (media_root / stored.relative_path).exists()


@pytest.mark.asyncio
async def test_photo_only_reply_uses_profile_and_budget_state():
    engine = ConversationEngine(StaticLLM())

    no_budget = await engine.handle_messages(client_summary="", recent_messages=["Клиент: [photo]"], stage="order", order_card=OrderCard())
    with_budget = await engine.handle_messages(client_summary="", recent_messages=["Клиент: [photo]"], stage="order", order_card=OrderCard(budget=5000))

    assert no_budget.messages == ["Вижу фото, буду ориентироваться на этот стиль. Подскажите, на какой бюджет ориентируемся?"]
    assert with_budget.messages == ["Вижу фото, буду ориентироваться на этот стиль. Подскажите, какие оттенки или цветы особенно нравятся?"]


def test_latest_client_photo_data_url_uses_latest_image_and_resizes(tmp_path):
    media_root = tmp_path / "media"
    first = store_image_bytes(_valid_png_bytes((255, 0, 0), size=(2048, 1024)), media_root=media_root, namespace="orders/1", max_bytes=20_000)
    latest = store_image_bytes(_valid_png_bytes((0, 0, 255), size=(32, 32)), media_root=media_root, namespace="orders/1", max_bytes=20_000)
    card = OrderCard(custom_fields={"client_photo_paths": [first.relative_path, latest.relative_path]})

    data_url = latest_client_photo_data_url(card, media_root=media_root, max_side_px=128)

    assert data_url is not None
    assert data_url.startswith("data:image/jpeg;base64,")
    decoded = base64.b64decode(data_url.removeprefix("data:image/jpeg;base64,"))
    with Image.open(io.BytesIO(decoded)) as image:
        assert max(image.size) <= 128
        assert image.getpixel((0, 0))[2] > image.getpixel((0, 0))[0]


def test_image_data_url_for_llm_converts_valid_image_to_jpeg(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(_valid_png_bytes(size=(4096, 1024)))

    data_url = image_data_url_for_llm(source, max_side_px=512)

    assert data_url.startswith("data:image/jpeg;base64,")
    decoded = base64.b64decode(data_url.removeprefix("data:image/jpeg;base64,"))
    with Image.open(io.BytesIO(decoded)) as image:
        assert image.format == "JPEG"
        assert max(image.size) <= 512


@pytest.mark.asyncio
async def test_photo_turn_sends_image_to_model_and_drops_forbidden_card_patch():
    llm = CapturingVisionLLM(
        '{"reply":"Вижу компактный красный букет, ориентируюсь на такой стиль.",'
        '"case_patch":{"budget":9999,"delivery_date":"2026-09-01","delivery_time":"12:00",'
        '"address":"с фото","payment_method":"transfer","colors":["красный"]},'
        '"next_step":"ask_budget","confidence":0.9}'
    )
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: хочу как здесь\n[photo]"],
        stage="order",
        order_card=OrderCard(),
        image_data_urls=["data:image/jpeg;base64,abc"],
    )

    assert llm.calls
    assert llm.calls[0]["kwargs"]["image_data_urls"] == ["data:image/jpeg;base64,abc"]
    assert "Бюджет, дату, адрес" in llm.calls[0]["prompt"]
    assert action.order_patch == {"colors": ["красный"]}
    assert action.messages == ["Вижу компактный красный букет, ориентируюсь на такой стиль."]


@pytest.mark.asyncio
async def test_photo_turn_filters_profile_codes_after_key_normalization():
    llm = CapturingVisionLLM(
        '{"reply":"Вижу светлый букет с розами.",'
        '"case_patch":{"date":"2026-09-01","time":"12:00","delivery_address":"Ленина 5",'
        '"customer_phone":"89990000001","budget":9000,"product_preferences":["розы"],"colors":["светлый"]},'
        '"next_step":"ask_budget","confidence":0.9}'
    )
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: [photo]"],
        stage="order",
        order_card=OrderCard(),
        image_data_urls=["data:image/jpeg;base64,abc"],
    )
    merged = OrderCard.from_dict({**OrderCard().to_dict(), **action.order_patch})

    assert action.order_patch == {"colors": ["розы"]}
    assert merged.delivery_date is None
    assert merged.delivery_time is None
    assert merged.address is None
    assert merged.sender_phone is None
    assert merged.budget is None


@pytest.mark.asyncio
async def test_photo_turn_filters_order_card_field_names_but_keeps_style_fields():
    llm = CapturingVisionLLM(
        '{"reply":"Вижу пастельные оттенки.",'
        '"case_patch":{"delivery_date":"2026-09-01","delivery_time":"12:00","address":"Ленина 5",'
        '"payment_method":"transfer","anonymous":true,"colors":["пастельный"]},'
        '"next_step":"ask_budget","confidence":0.9}'
    )
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: хочу как на фото [photo]"],
        stage="order",
        order_card=OrderCard(),
        image_data_urls=["data:image/jpeg;base64,abc"],
    )

    assert action.order_patch == {"colors": ["пастельный"]}


@pytest.mark.asyncio
async def test_without_image_patch_is_not_filtered():
    llm = CapturingVisionLLM(
        '{"reply":"Записала дату и адрес.",'
        '"case_patch":{"date":"2026-09-01","delivery_address":"Ленина 5","budget":9000},'
        '"next_step":"ask_time","confidence":0.9}'
    )
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: доставка 1 сентября на Ленина 5, бюджет 9000"],
        stage="order",
        order_card=OrderCard(),
    )

    assert action.order_patch == {"date": "2026-09-01", "delivery_address": "Ленина 5", "budget": 9000}


@pytest.mark.asyncio
async def test_photo_only_with_image_reaches_model_instead_of_template():
    llm = CapturingVisionLLM('{"reply":"Вижу пионы в светлых оттенках.","case_patch":{"colors":["пионы","светлый"]},"next_step":"ask_budget","confidence":0.9}')
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: [photo]"],
        stage="order",
        order_card=OrderCard(),
        image_data_urls=["data:image/jpeg;base64,abc"],
    )

    assert llm.calls[0]["kwargs"]["image_data_urls"] == ["data:image/jpeg;base64,abc"]
    assert action.messages == ["Вижу пионы в светлых оттенках."]
    assert action.order_patch == {"colors": ["пионы", "светлый"]}


@pytest.mark.asyncio
async def test_photo_only_without_image_uses_previous_template_without_model():
    llm = CapturingVisionLLM('{"reply":"should not be called"}')
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(client_summary="", recent_messages=["Клиент: [photo]"], stage="order", order_card=OrderCard())

    assert not llm.calls
    assert action.messages == ["Вижу фото, буду ориентироваться на этот стиль. Подскажите, на какой бюджет ориентируемся?"]


@pytest.mark.asyncio
async def test_generic_media_only_still_uses_media_fallback_without_model():
    llm = CapturingVisionLLM('{"reply":"should not be called"}')
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(client_summary="", recent_messages=["Клиент: [media]"], stage="order", order_card=OrderCard())

    assert not llm.calls
    assert action.messages == ["Вижу вложение. Напишите, пожалуйста, что именно нужно по заказу, и я помогу сориентироваться."]


@pytest.mark.asyncio
async def test_photo_prep_failure_without_image_data_keeps_dialogue_send_fallback(tmp_path):
    card = OrderCard(custom_fields={"client_photo_paths": ["orders/1/missing.jpg"]})
    assert latest_client_photo_data_url(card, media_root=tmp_path, max_side_px=128) is None
    llm = CapturingVisionLLM('{"reply":"should not be called"}')
    engine = ConversationEngine(llm)

    action = await engine.handle_messages(client_summary="", recent_messages=["Клиент: [photo]"], stage="order", order_card=card)

    assert action.kind == "send"
    assert not llm.calls
    assert action.messages == ["Вижу фото, буду ориентироваться на этот стиль. Подскажите, на какой бюджет ориентируемся?"]


@pytest.mark.asyncio
async def test_regular_text_turn_does_not_send_previous_image_to_model():
    llm = CapturingVisionLLM('{"reply":"Подскажите бюджет, пожалуйста.","case_patch":{},"next_step":"ask_budget","confidence":0.9}')
    engine = ConversationEngine(llm)

    await engine.handle_messages(
        client_summary="",
        recent_messages=["Клиент: бюджет 5000"],
        stage="order",
        order_card=OrderCard(custom_fields={"client_photo_paths": ["orders/1/photo.jpg"]}),
    )

    assert "image_data_urls" not in llm.calls[0]["kwargs"]
    assert "Клиент приложил фото" not in llm.calls[0]["prompt"]
