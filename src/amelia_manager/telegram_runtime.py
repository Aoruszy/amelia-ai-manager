from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from telethon import TelegramClient, events
from telethon.tl.types import SendMessageTypingAction

from amelia_manager.admin_notifier import format_admin_notification
from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.config import Settings
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.db.repository import ClientRecord, OrderRecord, SQLiteRepository, path_from_sqlite_url
from amelia_manager.date_formatting import _today_in_timezone
from amelia_manager.events import EventName
from amelia_manager.llm_client import GeminiClient
from amelia_manager.order_card import OrderCard, merge_order_patch, merge_order_state
from amelia_manager.order_extractor import extract_order_state_with_llm
from amelia_manager.order_request import format_admin_order_request
from amelia_manager.order_sheet import SheetsOrderAppender, append_order_to_sheet_if_needed, send_pending_sheet_rows
from amelia_manager.order_state import extract_order_state
from amelia_manager.outbound import (
    build_order_status_reply,
    is_opt_out_text,
    is_order_status_question,
    process_outbound_tick,
    schedule_followups_after_reply,
)
from amelia_manager.stock import build_stock_context, format_stock_ack, parse_stock_text
from amelia_manager.stock_source import ManualStockSource, SheetsStockSource, StockSnapshot, StockSource
from amelia_manager.observability import EventRecorder, configure_logging
from amelia_manager.stats_report import format_stats_report, parse_stats_days
from amelia_manager.telegram_login import get_session_path


LOGGER = logging.getLogger("amelia_manager.telegram_runtime")


def is_stock_command(text: str) -> bool:
    stripped = text.strip().lower()
    return stripped.startswith("/stock") or stripped.startswith("наличие на сегодня")


def handle_stock_command(
    repo: SQLiteRepository,
    *,
    sender_id: int,
    text: str,
    today: date | None = None,
    company_profile: CompanyProfile | None = None,
) -> str:
    timezone_name = (company_profile or load_company_profile("amelia_flowers")).timezone_name
    stock_date = today or _today_in_timezone(timezone_name)
    items = parse_stock_text(text)
    if items:
        repo.replace_daily_stock(stock_date=stock_date, items=items, updated_by=sender_id)
    source_type = (company_profile.stock_source.type if company_profile is not None else "manual")
    return format_stock_ack(items, source_type=source_type)


def build_stock_source(repo: SQLiteRepository, company_profile: CompanyProfile) -> StockSource:
    if company_profile.stock_source.type == "sheets" and company_profile.stock_source.sheets is not None:
        return SheetsStockSource(repo, config=company_profile.stock_source.sheets, timezone_name=company_profile.timezone_name)
    return ManualStockSource(repo)


def handle_admin_control_command(repo: SQLiteRepository, text: str, *, admin_id: int) -> str:
    parts = text.strip().split()
    if not parts:
        return "Неизвестная команда."
    command = parts[0].lower()
    if command == "/paused":
        paused = repo.list_paused_clients()
        if not paused:
            return "Диалогов на паузе нет."
        lines = ["Диалоги на паузе:"]
        for record in paused:
            username = f" @{record.username}" if record.username else ""
            lines.append(f"• {record.telegram_id}{username} — {record.stage}")
        return "\n".join(lines)
    if command not in {"/pause", "/resume"} or len(parts) < 2:
        return "Используйте /pause <telegram_id>, /resume <telegram_id> или /paused."
    try:
        telegram_id = int(parts[1])
    except ValueError:
        return "telegram_id должен быть числом."
    client = repo.get_client_by_telegram_id(telegram_id)
    if client is None:
        return "Клиент не найден."
    if command == "/pause":
        repo.pause_client(client_id=client.id, paused_by=str(admin_id), reason="manual")
        return f"Пауза включена для {telegram_id}."
    repo.resume_client(client_id=client.id, reason="manual")
    return f"Вернул боту диалог {telegram_id}."


def get_current_stock_snapshot(source: StockSource) -> StockSnapshot:
    return source.fetch()


def update_active_order_from_messages(
    repo: SQLiteRepository,
    *,
    client_id: int,
    recent_messages: list[str],
    company_profile: CompanyProfile | None = None,
    today: date | None = None,
) -> OrderCard:
    active = repo.get_active_order(client_id=client_id)
    latest_text = _last_client_text(recent_messages)
    if active and (
        should_start_new_order(latest_text, active.card)
        or _has_explicit_restart_in_history(recent_messages)
        or _completed_order_has_new_start_in_history(active.card, recent_messages)
    ):
        repo.close_active_orders(client_id=client_id)
        active = None
    order = active or repo.get_or_create_active_order(client_id=client_id)
    messages_for_extraction = _messages_for_order_extraction(order.card, recent_messages)
    extracted = extract_order_state(
        messages_for_extraction,
        today=today,
        timezone_name=(company_profile or load_company_profile("amelia_flowers")).timezone_name,
    )
    card = merge_order_state(order.card, extracted)
    repo.update_order_card(order_id=order.id, card=card)
    return card


async def update_active_order_from_messages_with_llm(
    repo: SQLiteRepository,
    *,
    llm,
    client_id: int,
    recent_messages: list[str],
    company_profile: CompanyProfile | None = None,
    today: date | None = None,
) -> OrderCard:
    active = repo.get_active_order(client_id=client_id)
    latest_text = _last_client_text(recent_messages)
    if active and (
        should_start_new_order(latest_text, active.card)
        or _has_explicit_restart_in_history(recent_messages)
        or _completed_order_has_new_start_in_history(active.card, recent_messages)
    ):
        repo.close_active_orders(client_id=client_id)
        active = None
    order = active or repo.get_or_create_active_order(client_id=client_id)
    messages_for_extraction = _messages_for_order_extraction(order.card, recent_messages)
    profile = company_profile or load_company_profile("amelia_flowers")
    extracted = await extract_order_state_with_llm(
        llm,
        messages_for_extraction,
        company_profile=profile,
        today=today,
        timezone_name=profile.timezone_name,
    )
    card = merge_order_state(order.card, extracted)
    repo.update_order_card(order_id=order.id, card=card)
    return card


async def update_active_order_from_messages_with_optional_llm(
    repo: SQLiteRepository,
    *,
    settings: Settings,
    llm,
    client_id: int,
    recent_messages: list[str],
    company_profile: CompanyProfile | None = None,
    today: date | None = None,
) -> OrderCard:
    if should_use_llm_extractor(settings, company_profile=company_profile):
        return await update_active_order_from_messages_with_llm(
            repo,
            llm=llm,
            client_id=client_id,
            recent_messages=recent_messages,
            company_profile=company_profile,
            today=today,
        )
    return update_active_order_from_messages(
        repo,
        client_id=client_id,
        recent_messages=recent_messages,
        company_profile=company_profile,
        today=today,
    )


def should_use_llm_extractor(settings: Settings, *, company_profile: CompanyProfile | None = None) -> bool:
    return bool(getattr(settings, "llm_extractor_enabled", False))


def should_start_new_order(latest_client_text: str, existing_card: OrderCard) -> bool:
    text = latest_client_text.lower().replace("ё", "е").strip()
    generic_new_request = _looks_like_order_start(text)
    has_existing_order = any(
        [
            existing_card.budget,
            existing_card.fulfillment_type,
            existing_card.delivery_date,
            existing_card.delivery_time,
            existing_card.address,
            existing_card.sender_phone,
        ]
    )
    if generic_new_request and has_existing_order:
        return True

    if _is_greeting_order_restart(text) and has_existing_order:
        return True

    rich_new_request = _looks_like_order_start(text)
    rich_order_details = sum(
        bool(flag)
        for flag in (
            re.search(r"\bдо\s*\d{3,6}\b|\bбюджет\b", text),
            re.search(r"\b\d{1,2}[:.]\d{2}\b", text),
            "самовывоз" in text or "доставка" in text,
            re.search(r"\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b", text),
            "цвет" in text,
        )
    )
    previous_order_is_effectively_done = existing_card.admin_request_sent or existing_card.is_ready_for_admin_request()
    return previous_order_is_effectively_done and rich_new_request and rich_order_details >= 2


def _last_client_text(recent_messages: list[str]) -> str:
    for message in reversed(recent_messages):
        if message.lower().startswith("клиент:"):
            return message.split(":", 1)[1].strip()
    return recent_messages[-1].strip() if recent_messages else ""


def _looks_like_order_start(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "нужен букет",
            "нужны цветы",
            "хочу букет",
            "хочу цветы",
            "цветы купить",
            "купить цветы",
            "хочу букет купить",
            "заказать букет",
        )
    ) or _is_greeting_order_restart(text)


def _is_greeting_order_restart(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" !?.")
    has_greeting = bool(
        re.match(r"^(здравствуй|здравствуйте|добрый\s+день|доброе\s+утро|добрый\s+вечер|привет)\b", normalized)
    )
    return has_greeting and _looks_like_fulfillment_request(normalized)


def _looks_like_fulfillment_request(text: str) -> bool:
    return bool(re.search(r"\bдоставк\w*\b", text) or re.search(r"\bсамовывоз\w*\b", text))


def _has_explicit_restart_in_history(recent_messages: list[str]) -> bool:
    client_turns: list[tuple[int, str]] = []
    for index, message in enumerate(recent_messages):
        if message.lower().startswith("клиент:"):
            client_turns.append((index, message.split(":", 1)[1].lower().replace("ё", "е").strip()))
    if not client_turns:
        return False

    latest_index, latest_text = client_turns[-1]
    if _is_greeting_order_restart(latest_text):
        return latest_index > 0
    if not _looks_like_fulfillment_request(latest_text):
        return False
    if len(client_turns) < 2:
        return False
    previous_index, previous_text = client_turns[-2]
    return previous_index < latest_index and _is_greeting_only_text(previous_text)


def _is_greeting_only_text(text: str) -> bool:
    normalized = text.lower().replace("ё", "е").strip(" !?.")
    return normalized in {"здравствуй", "здравствуйте", "добрый день", "доброе утро", "добрый вечер", "привет"}

def _completed_order_has_new_start_in_history(card: OrderCard, recent_messages: list[str]) -> bool:
    if not (card.admin_request_sent or card.client_summary_sent or card.is_ready_for_admin_request()):
        return False
    latest_start_index = _latest_order_start_index(recent_messages)
    return latest_start_index is not None and latest_start_index > 0


def _messages_since_latest_order_start(recent_messages: list[str]) -> list[str]:
    latest_start_index = _latest_order_start_index(recent_messages)
    if latest_start_index is None:
        return recent_messages
    return recent_messages[latest_start_index:]


def _messages_for_order_extraction(existing_card: OrderCard, recent_messages: list[str]) -> list[str]:
    latest_text = _last_client_text(recent_messages)
    latest_state = extract_order_state([f"Клиент: {latest_text}"])
    if (
        existing_card.fulfillment_type
        and latest_state.fulfillment_type
        and latest_state.fulfillment_type != existing_card.fulfillment_type
    ):
        return [f"Клиент: {latest_text}"]
    return _messages_since_latest_order_start(recent_messages)


def _latest_order_start_index(recent_messages: list[str]) -> int | None:
    latest_start_index: int | None = None
    for index, message in enumerate(recent_messages):
        if not message.lower().startswith("клиент:"):
            continue
        text = message.split(":", 1)[1].lower().replace("ё", "е")
        if _looks_like_order_start(text):
            latest_start_index = index
    return latest_start_index


def derive_client_state(card: OrderCard, *, last_client_text: str) -> tuple[str, str]:
    if card.is_ready_for_admin_request() or card.client_summary_sent or card.admin_request_sent:
        stage = "order_ready"
    elif any(
        [
            card.budget,
            card.colors,
            card.fulfillment_type,
            card.delivery_date,
            card.delivery_time,
            card.address,
            card.sender_phone,
        ]
    ):
        stage = "order_in_progress"
    else:
        stage = "new_lead"
    parts: list[str] = []
    if card.budget:
        parts.append(f"бюджет {card.budget}")
    if card.fulfillment_type:
        parts.append("самовывоз" if card.fulfillment_type == "pickup" else "доставка")
    if card.delivery_date:
        parts.append(f"дата {card.delivery_date}")
    if card.delivery_time:
        parts.append(f"время {card.delivery_time}")
    if card.colors:
        parts.append("пожелания: " + ", ".join(card.colors))
    if card.address:
        parts.append(f"адрес {card.address}")
    if card.sender_name or card.sender_phone:
        parts.append(f"контакт клиента {card.sender_name or ''} {card.sender_phone or ''}".strip())
    summary = "; ".join(parts) if parts else (last_client_text[:160] if last_client_text else "")
    return stage, summary[:500]


def build_admin_order_request_if_needed(
    repo: SQLiteRepository,
    *,
    order: OrderRecord,
    client_label: str,
    company_profile: CompanyProfile | None = None,
    mark_sent: bool = True,
) -> str | None:
    if order.card.admin_request_sent or not order.card.is_ready_for_admin_request():
        return None
    text = format_admin_order_request(
        order_id=order.id,
        client_label=client_label,
        card=order.card,
        company_profile=company_profile,
    )
    if mark_sent:
        repo.update_order_card(
            order_id=order.id,
            card=OrderCard.from_dict(
                {
                    **order.card.to_dict(),
                    "admin_request_sent": True,
                    "client_summary_sent": True,
                }
            ),
        )
    return text


@dataclass(frozen=True)
class IncomingMessage:
    sender_id: int
    text: str
    is_private: bool
    outgoing: bool


async def send_admin_order_request_if_ready(
    telegram_client,
    *,
    repo: SQLiteRepository,
    order: OrderRecord,
    admin_chat_id: int,
    client_label: str,
    company_profile: CompanyProfile | None = None,
    order_sheet_appender: SheetsOrderAppender | None = None,
) -> bool:
    admin_order_text = build_admin_order_request_if_needed(
        repo,
        order=order,
        client_label=client_label,
        company_profile=company_profile,
        mark_sent=False,
    )
    if not admin_order_text:
        return False
    await telegram_client.send_message(admin_chat_id, admin_order_text)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard.from_dict(
            {
                **order.card.to_dict(),
                "admin_request_sent": True,
                "client_summary_sent": True,
            }
        ),
    )
    if company_profile is not None:
        refreshed = repo.get_active_order(client_id=order.client_id) or order
        append_order_to_sheet_if_needed(
            repo,
            order=refreshed,
            client_label=client_label,
            company_profile=company_profile,
            appender=order_sheet_appender,
        )
    return True


async def send_pending_admin_requests(
    telegram_client,
    *,
    repo: SQLiteRepository,
    admin_chat_id: int,
    company_profile: CompanyProfile | None = None,
) -> int:
    sent = 0
    for order, client_record in repo.list_active_orders_with_clients():
        if order.card.admin_request_sent or not order.card.is_ready_for_admin_request():
            continue
        client_label = (
            f"@{client_record.username} / {client_record.telegram_id}"
            if client_record.username
            else str(client_record.telegram_id)
        )
        if await send_admin_order_request_if_ready(
            telegram_client,
            repo=repo,
            order=order,
            admin_chat_id=admin_chat_id,
            client_label=client_label,
            company_profile=company_profile,
        ):
            sent += 1
    return sent


def event_text_with_media_placeholder(event) -> str:
    text = (getattr(event, "raw_text", None) or "").strip()
    placeholders: list[str] = []
    if getattr(event, "photo", None) is not None:
        placeholders.append("[photo]")
    elif getattr(event, "media", None) is not None:
        placeholders.append("[media]")
    return "\n".join([part for part in [text, *placeholders] if part])


class SenderUsernameCache:
    def __init__(self, *, max_size: int = 1000) -> None:
        self.max_size = max_size
        self._items: OrderedDict[int, str | None] = OrderedDict()

    def set(self, sender_id: int, username: str | None) -> None:
        self._items[sender_id] = username
        self._items.move_to_end(sender_id)
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)

    def get(self, sender_id: int) -> str | None:
        if sender_id not in self._items:
            return None
        self._items.move_to_end(sender_id)
        return self._items[sender_id]


class PerSenderDebounceProcessor:
    """Buffers rapid incoming messages and processes one serialized turn per sender."""

    def __init__(
        self,
        *,
        buffer_seconds: float,
        process_turn: Callable[[int, list[str]], Awaitable[None]],
        first_buffer_seconds: float | None = None,
    ) -> None:
        self.buffer_seconds = buffer_seconds
        self.first_buffer_seconds = buffer_seconds if first_buffer_seconds is None else first_buffer_seconds
        self.process_turn = process_turn
        self._buffers: dict[int, list[str]] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, *, sender_id: int, text: str) -> None:
        async with self._lock:
            self._buffers.setdefault(sender_id, []).append(text)
            task = self._tasks.get(sender_id)
            if task is None or task.done():
                self._tasks[sender_id] = asyncio.create_task(self._run_sender(sender_id))

    async def wait_idle(self) -> None:
        while True:
            async with self._lock:
                tasks = [task for task in self._tasks.values() if not task.done()]
            if not tasks:
                return
            await asyncio.gather(*tasks)

    async def active_sender_ids(self) -> set[int]:
        async with self._lock:
            return set(self._buffers.keys())

    async def _run_sender(self, sender_id: int) -> None:
        first_turn = True
        while True:
            await asyncio.sleep(self.first_buffer_seconds if first_turn else self.buffer_seconds)
            first_turn = False
            async with self._lock:
                messages = self._buffers.pop(sender_id, [])
            if messages:
                try:
                    await self.process_turn(sender_id, messages)
                except Exception as exc:  # noqa: BLE001 - keep listener alive after a failed turn
                    LOGGER.exception(
                        "turn_processing_failed",
                        extra={"event": "turn_processing_failed", "client_id": sender_id, "payload": {"reason": repr(exc)}},
                    )
            async with self._lock:
                if not self._buffers.get(sender_id):
                    self._tasks.pop(sender_id, None)
                    return


def should_process_incoming(message: IncomingMessage, settings: Settings) -> bool:
    if message.outgoing:
        return False
    if not message.is_private:
        return False
    if not message.text.strip():
        return False
    if settings.allow_only_test_users and message.sender_id not in settings.allowlist_ids:
        return False
    return True


def persist_incoming_message(
    repo: SQLiteRepository,
    message: IncomingMessage,
    *,
    username: str | None,
) -> ClientRecord:
    client = repo.upsert_client(telegram_id=message.sender_id, username=username)
    repo.add_message(client_id=client.id, direction="in", text=message.text)
    return client


async def send_typing_and_messages(
    client,
    *,
    sender_id: int,
    messages: list[str],
    initial_delay: float,
    max_initial_delay: float | None = None,
    between_delay: float = 1.5,
    max_chars: int = 400,
    sleep=asyncio.sleep,
    random_between=random.uniform,
) -> None:
    actual_initial_delay = initial_delay
    if max_initial_delay is not None and max_initial_delay > initial_delay:
        actual_initial_delay = random_between(initial_delay, max_initial_delay)
    async with client.action(sender_id, SendMessageTypingAction()):
        await sleep(actual_initial_delay)
    for message in messages:
        await client.send_message(sender_id, _limit_reply_chars(message, max_chars=max_chars))
        await sleep(between_delay)


def _limit_reply_chars(message: str, *, max_chars: int) -> str:
    if len(message) <= max_chars:
        return message
    if max_chars <= 1:
        return "…"[:max_chars]
    return message[: max_chars - 1].rstrip() + "…"


def is_within_work_hours(now: datetime, *, settings: Settings) -> bool:
    start = _parse_hhmm(settings.work_hours_start)
    end = _parse_hhmm(settings.work_hours_end)
    current = now.timetz().replace(tzinfo=None)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def build_off_hours_reply(*, settings: Settings) -> str:
    opening = settings.work_hours_start.lstrip("0") or settings.work_hours_start
    return f"Сейчас менеджер не на связи. Ответим с {opening}, как только начнётся рабочий день."


async def weekly_stats_loop(
    telegram_client,
    *,
    repo: SQLiteRepository,
    admin_chat_id: int,
    settings: Settings,
    timezone_name: str,
    sleep=asyncio.sleep,
) -> None:
    sent_for_date: date | None = None
    while True:
        now = datetime.now(ZoneInfo(timezone_name))
        if now.weekday() == 0 and is_within_work_hours(now, settings=settings) and sent_for_date != now.date():
            await telegram_client.send_message(admin_chat_id, format_stats_report(repo, days=7, today=now.date(), timezone_name=timezone_name))
            sent_for_date = now.date()
        await sleep(3600)


async def outbound_scheduler_loop(
    telegram_client,
    *,
    repo: SQLiteRepository,
    settings: Settings,
    company_profile: CompanyProfile,
    debounce_processor: PerSenderDebounceProcessor,
    llm_client: GeminiClient,
    sleep=asyncio.sleep,
) -> None:
    while True:
        active_telegram_ids = await debounce_processor.active_sender_ids()
        active_clients = {
            client.id
            for telegram_id in active_telegram_ids
            if (client := repo.get_client_by_telegram_id(telegram_id)) is not None
        }
        await process_outbound_tick(
            telegram_client,
            repo=repo,
            settings=settings,
            company_profile=company_profile,
            now=datetime.now(ZoneInfo(company_profile.timezone_name)),
            active_buffers=active_clients,
            llm_client=llm_client,
        )
        await sleep(settings.scheduler_interval_minutes * 60)


def should_send_off_hours_reply(repo: SQLiteRepository, *, client_id: int, now: datetime, settings: Settings) -> bool:
    """Return false after this client already received the current off-hours notice."""
    reply = build_off_hours_reply(settings=settings)
    boundary = _last_work_hours_boundary(now, settings=settings)
    for message in reversed(repo.list_messages(client_id=client_id, limit=50)):
        if message.direction != "out" or message.text != reply:
            continue
        try:
            sent_at = datetime.fromisoformat(message.created_at).replace(tzinfo=None)
        except ValueError:
            return False
        return sent_at < boundary.replace(tzinfo=None)
    return True


def _last_work_hours_boundary(now: datetime, *, settings: Settings) -> datetime:
    start = _parse_hhmm(settings.work_hours_start)
    end = _parse_hhmm(settings.work_hours_end)
    current = now.timetz().replace(tzinfo=None)
    boundary_date = now.date()
    if current < start:
        boundary_date = boundary_date - timedelta(days=1)
    return datetime.combine(boundary_date, end, tzinfo=now.tzinfo)


def _parse_hhmm(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))


async def run_listener(settings: Settings) -> None:
    configure_logging(settings.log_level)
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY is required")
    if not settings.admin_chat_id:
        raise RuntimeError("ADMIN_CHAT_ID is required")

    session_path = get_session_path(settings)
    client = TelegramClient(str(session_path), settings.telegram_api_id, settings.telegram_api_hash)
    llm = GeminiClient(api_key=settings.llm_api_key, model=settings.llm_model)
    company_profile = load_company_profile(settings.company_profile_name)
    engine = ConversationEngine(llm, company_profile=company_profile)
    repo = SQLiteRepository(path_from_sqlite_url(settings.database_url))
    repo.initialize()
    event_recorder = EventRecorder(repo)
    stock_source = build_stock_source(repo, company_profile)
    cleanup_result = repo.cleanup_pii_older_than(retention_days=settings.pii_retention_days)
    if cleanup_result.deleted_messages or cleanup_result.anonymized_orders or cleanup_result.deleted_events:
        LOGGER.info(
            "retention_cleanup",
            extra={
                "event": "retention_cleanup",
                "payload": {
                    "deleted_messages": cleanup_result.deleted_messages,
                    "anonymized_orders": cleanup_result.anonymized_orders,
                    "deleted_events": cleanup_result.deleted_events,
                },
            },
        )

    sender_usernames = SenderUsernameCache(max_size=1000)

    async def process_customer_turn(sender_id: int, texts: list[str]) -> None:
        username = sender_usernames.get(sender_id)
        existing_client = repo.get_client_by_telegram_id(sender_id)
        db_client = repo.upsert_client(telegram_id=sender_id, username=username)
        cancelled_followups = repo.cancel_pending_followups(client_id=db_client.id)
        for cancelled in cancelled_followups:
            event_recorder.record(
                EventName.FOLLOWUP_CANCELLED,
                client_id=db_client.id,
                order_id=cancelled.order_id,
                payload={"kind": cancelled.kind, "reason": "client_replied"},
            )
        sent_followups = repo.list_events(client_id=db_client.id, event=EventName.FOLLOWUP_SENT)
        if sent_followups:
            event_recorder.record(
                EventName.FOLLOWUP_REPLIED,
                client_id=db_client.id,
                payload={"kind": json.loads(sent_followups[-1].payload_json or "{}").get("kind")},
            )
        if any(is_opt_out_text(text) for text in texts):
            repo.mark_client_opted_out(client_id=db_client.id)
            event_recorder.record(EventName.OPT_OUT, client_id=db_client.id)
        if existing_client is None:
            event_recorder.record(EventName.DIALOG_STARTED, client_id=db_client.id)
        for text in texts:
            repo.add_message(client_id=db_client.id, direction="in", text=text)
            event_recorder.record(
                EventName.MESSAGE_RECEIVED,
                client_id=db_client.id,
                payload={"has_media": "[photo]" in text or "[media]" in text},
            )
        if db_client.bot_paused_at:
            return
        now = datetime.now(ZoneInfo(company_profile.timezone_name))
        if (
            settings.auto_reply_enabled
            and not is_within_work_hours(now, settings=settings)
            and should_send_off_hours_reply(repo, client_id=db_client.id, now=now, settings=settings)
        ):
            reply = build_off_hours_reply(settings=settings)
            await send_typing_and_messages(
                client,
                sender_id=sender_id,
                messages=[reply],
                initial_delay=settings.min_reply_delay_seconds,
                max_initial_delay=settings.max_reply_delay_seconds,
                max_chars=settings.max_reply_chars,
            )
            repo.add_message(
                client_id=db_client.id,
                direction="out",
                text=_limit_reply_chars(reply, max_chars=settings.max_reply_chars),
            )
            event_recorder.record(EventName.OFF_HOURS_REPLY, client_id=db_client.id)
            event_recorder.record(EventName.REPLY_SENT, client_id=db_client.id, payload={"llm_used": False})
            return
        recent_db_messages = repo.list_messages(
            client_id=db_client.id,
            limit=settings.conversation_history_limit,
            since_days=settings.conversation_memory_days,
        )
        recent_messages = [
            f"{'Клиент' if message.direction == 'in' else 'Менеджер'}: {message.text}"
            for message in recent_db_messages
        ]
        if is_order_status_question("\n".join(texts)):
            active_order_for_status = repo.get_active_order(client_id=db_client.id)
            reply = build_order_status_reply(repo, client_id=db_client.id, company_profile=company_profile)
            if settings.auto_reply_enabled:
                await send_typing_and_messages(
                    client,
                    sender_id=sender_id,
                    messages=[reply],
                    initial_delay=settings.min_reply_delay_seconds,
                    max_initial_delay=settings.max_reply_delay_seconds,
                    max_chars=settings.max_reply_chars,
                )
            repo.add_message(client_id=db_client.id, direction="out", text=_limit_reply_chars(reply, max_chars=settings.max_reply_chars))
            event_recorder.record(EventName.STATUS_ANSWERED, client_id=db_client.id, order_id=active_order_for_status.id if active_order_for_status else None)
            event_recorder.record(EventName.REPLY_SENT, client_id=db_client.id, order_id=active_order_for_status.id if active_order_for_status else None, payload={"llm_used": False, "intent": "status"})
            return
        order_card = await update_active_order_from_messages_with_optional_llm(
            repo,
            settings=settings,
            llm=llm,
            client_id=db_client.id,
            recent_messages=recent_messages,
            company_profile=company_profile,
        )
        stock_snapshot = get_current_stock_snapshot(stock_source)
        if stock_snapshot.source_name == "sqlite_fallback":
            event_recorder.record(
                EventName.STOCK_SOURCE_DEGRADED,
                client_id=db_client.id,
                payload={"source_name": stock_snapshot.source_name},
            )
        stock_context = build_stock_context(
            items=stock_snapshot.items,
            colors=order_card.colors,
            desired_text="\n".join(recent_messages),
            stock_date=stock_snapshot.fetched_at.date() if stock_snapshot.items else None,
            timezone_name=company_profile.timezone_name,
        )

        action = await engine.handle_messages(
            client_summary=db_client.summary or "Новый или текущий клиент Telegram.",
            recent_messages=recent_messages,
            stage=db_client.stage,
            stock_context=stock_context,
            order_card=order_card,
        )

        if action.order_patch:
            active_order_for_patch = repo.get_active_order(client_id=db_client.id)
            if active_order_for_patch:
                order_card = merge_order_patch(active_order_for_patch.card, action.order_patch)
                repo.update_order_card(order_id=active_order_for_patch.id, card=order_card)
                for field_code in action.order_patch.keys():
                    event_recorder.record(
                        EventName.STEP_COMPLETED,
                        client_id=db_client.id,
                        order_id=active_order_for_patch.id,
                        payload={"field_code": field_code},
                    )
        stage, summary = derive_client_state(order_card, last_client_text="\n".join(texts))
        repo.update_client_state(client_id=db_client.id, stage=stage, summary=summary)

        client_label = f"@{username} / {sender_id}" if username else str(sender_id)
        active_order = repo.get_active_order(client_id=db_client.id)
        if active_order and active_order.card.is_ready_for_admin_request() and not active_order.card.admin_request_sent:
            event_recorder.record(
                EventName.ORDER_READY,
                client_id=db_client.id,
                order_id=active_order.id,
                payload={"budget": active_order.card.budget, "fulfillment_type": active_order.card.fulfillment_type},
            )
        if active_order and settings.auto_reply_enabled:
            if await send_admin_order_request_if_ready(
                client,
                repo=repo,
                order=active_order,
                admin_chat_id=settings.admin_chat_id,
                client_label=client_label,
                company_profile=company_profile,
            ):
                event_recorder.record(EventName.ADMIN_REQUEST_SENT, client_id=db_client.id, order_id=active_order.id)

        if action.kind == "human_takeover":
            repo.pause_client(client_id=db_client.id, paused_by="auto", reason="escalation")
        if settings.auto_reply_enabled and action.kind in {"human_takeover", "human_review"}:
            event_recorder.record(
                EventName.ESCALATED,
                client_id=db_client.id,
                order_id=active_order.id if active_order else None,
                payload={
                    "risk_level": action.risk_level.value,
                    "risk_category": action.risk_category.value if action.risk_category else None,
                    "reason": action.safety_reasons[0] if action.safety_reasons else action.kind,
                },
            )
            await client.send_message(
                settings.admin_chat_id,
                format_admin_notification(
                    title="Нужен ручной контроль",
                    client_label=client_label,
                    stage="new_lead",
                    risk_level=action.risk_level,
                    summary="AI передал диалог человеку.",
                    last_message="\n".join(texts),
                    company_profile=company_profile,
                ),
            )

        if settings.auto_reply_enabled:
            await send_typing_and_messages(
                client,
                sender_id=sender_id,
                messages=action.messages,
                initial_delay=settings.min_reply_delay_seconds,
                max_initial_delay=settings.max_reply_delay_seconds,
                max_chars=settings.max_reply_chars,
            )
            for message in action.messages:
                repo.add_message(
                    client_id=db_client.id,
                    direction="out",
                    text=_limit_reply_chars(message, max_chars=settings.max_reply_chars),
                )
            if any(reason.startswith("llm_error") for reason in action.safety_reasons):
                event_recorder.record(EventName.LLM_FAILED, client_id=db_client.id, order_id=active_order.id if active_order else None, payload={"stage": "reply"})
            if action.safety_triggered_reasons:
                event_recorder.record(
                    EventName.SAFETY_TRIGGERED,
                    client_id=db_client.id,
                    order_id=active_order.id if active_order else None,
                    payload={"reasons": action.safety_triggered_reasons, "retry_succeeded": action.safety_retry_succeeded is True},
                )
            event_recorder.record(
                EventName.REPLY_SENT,
                client_id=db_client.id,
                order_id=active_order.id if active_order else None,
                payload={
                    "next_step": action.next_step,
                    "intent": action.intent,
                    "confidence": action.confidence,
                    "llm_used": action.confidence is not None or action.intent is not None,
                },
            )
            refreshed_client = repo.get_client_by_id(db_client.id) or db_client
            inbound_count = sum(1 for message in repo.list_messages(client_id=db_client.id, limit=30) if message.direction == "in")
            if active_order:
                schedule_followups_after_reply(
                    repo,
                    client=refreshed_client,
                    order=active_order,
                    inbound_count=inbound_count,
                    action_kind=action.kind,
                    now=datetime.now(ZoneInfo(company_profile.timezone_name)),
                    company_profile=company_profile,
                )
        else:
            LOGGER.info(
                "dry_run_reply",
                extra={"event": "dry_run_reply", "client_id": db_client.id, "order_id": active_order.id if active_order else None, "payload": {"reason": action.kind}},
            )

    debounce_processor = PerSenderDebounceProcessor(
        buffer_seconds=settings.message_buffer_seconds,
        first_buffer_seconds=min(settings.message_buffer_seconds, 2),
        process_turn=process_customer_turn,
    )

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        sender = await event.get_sender()
        sender_id = int(sender.id)
        incoming = IncomingMessage(
            sender_id=sender_id,
            text=event_text_with_media_placeholder(event),
            is_private=event.is_private,
            outgoing=bool(event.out),
        )
        if not should_process_incoming(incoming, settings):
            return

        if sender_id == int(settings.admin_chat_id) and is_stock_command(incoming.text):
            ack = handle_stock_command(repo, sender_id=sender_id, text=incoming.text, company_profile=company_profile)
            await client.send_message(sender_id, ack)
            return

        if sender_id == int(settings.admin_chat_id) and incoming.text.strip().lower().startswith("/stats"):
            await client.send_message(sender_id, format_stats_report(repo, days=parse_stats_days(incoming.text), timezone_name=company_profile.timezone_name))
            return

        if sender_id == int(settings.admin_chat_id) and incoming.text.strip().lower().split(maxsplit=1)[0] in {"/pause", "/resume", "/paused"}:
            await client.send_message(sender_id, handle_admin_control_command(repo, incoming.text, admin_id=sender_id))
            return

        sender_usernames.set(sender_id, getattr(sender, "username", None))
        await debounce_processor.enqueue(sender_id=sender_id, text=incoming.text)

    await client.start(phone=settings.telegram_phone)
    me = await client.get_me()
    LOGGER.info("listener_started", extra={"event": "listener_started", "payload": {"auto_reply": settings.auto_reply_enabled}})
    if settings.auto_reply_enabled:
        pending_sent = await send_pending_admin_requests(
            client,
            repo=repo,
            admin_chat_id=settings.admin_chat_id,
            company_profile=company_profile,
        )
        if pending_sent:
            LOGGER.info("pending_admin_requests_sent", extra={"event": "pending_admin_requests_sent", "payload": {"count": pending_sent}})
        pending_sheet_rows = send_pending_sheet_rows(repo, company_profile=company_profile)
        if pending_sheet_rows:
            LOGGER.info("pending_sheet_rows_sent", extra={"event": "pending_sheet_rows_sent", "payload": {"count": pending_sheet_rows}})
        asyncio.create_task(
            weekly_stats_loop(
                client,
                repo=repo,
                admin_chat_id=settings.admin_chat_id,
                settings=settings,
                timezone_name=company_profile.timezone_name,
            )
        )
        asyncio.create_task(
            outbound_scheduler_loop(
                client,
                repo=repo,
                settings=settings,
                company_profile=company_profile,
                debounce_processor=debounce_processor,
                llm_client=llm,
            )
        )
    await client.run_until_disconnected()


def main() -> None:
    asyncio.run(run_listener(Settings()))


if __name__ == "__main__":
    main()
