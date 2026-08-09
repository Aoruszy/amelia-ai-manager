from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from telethon import TelegramClient, events
from telethon.tl.types import SendMessageTypingAction

from amelia_manager.admin_notifier import format_admin_notification
from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.config import Settings
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.db.repository import ClientRecord, OrderRecord, SQLiteRepository, path_from_sqlite_url
from amelia_manager.llm_client import GeminiClient
from amelia_manager.order_card import OrderCard, merge_order_state
from amelia_manager.order_extractor import extract_order_state_with_llm
from amelia_manager.order_request import format_admin_order_request
from amelia_manager.order_state import extract_order_state
from amelia_manager.stock import build_stock_context, format_stock_ack, parse_stock_text
from amelia_manager.telegram_login import get_session_path


def is_stock_command(text: str) -> bool:
    stripped = text.strip().lower()
    return stripped.startswith("/stock") or stripped.startswith("наличие на сегодня")


def handle_stock_command(
    repo: SQLiteRepository,
    *,
    sender_id: int,
    text: str,
    today: date | None = None,
) -> str:
    stock_date = today or date.today()
    items = parse_stock_text(text)
    if items:
        repo.replace_daily_stock(stock_date=stock_date, items=items, updated_by=sender_id)
    return format_stock_ack(items)


def update_active_order_from_messages(
    repo: SQLiteRepository,
    *,
    client_id: int,
    recent_messages: list[str],
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
    extracted = extract_order_state(messages_for_extraction)
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
    extracted = await extract_order_state_with_llm(llm, messages_for_extraction, company_profile=company_profile)
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
) -> OrderCard:
    if should_use_llm_extractor(settings, company_profile=company_profile):
        return await update_active_order_from_messages_with_llm(
            repo,
            llm=llm,
            client_id=client_id,
            recent_messages=recent_messages,
            company_profile=company_profile,
        )
    return update_active_order_from_messages(repo, client_id=client_id, recent_messages=recent_messages)


def should_use_llm_extractor(settings: Settings, *, company_profile: CompanyProfile | None = None) -> bool:
    if bool(getattr(settings, "llm_extractor_enabled", False)):
        return True
    return bool(company_profile and company_profile.business_type != "florist")


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


def build_admin_order_request_if_needed(
    repo: SQLiteRepository,
    *,
    order: OrderRecord,
    client_label: str,
    mark_sent: bool = True,
) -> str | None:
    if order.card.admin_request_sent or not order.card.is_ready_for_admin_request():
        return None
    text = format_admin_order_request(order_id=order.id, client_label=client_label, card=order.card)
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


def event_text_with_media_placeholder(event) -> str:
    text = (getattr(event, "raw_text", None) or "").strip()
    placeholders: list[str] = []
    if getattr(event, "photo", None) is not None:
        placeholders.append("[photo]")
    elif getattr(event, "media", None) is not None:
        placeholders.append("[media]")
    return "\n".join([part for part in [text, *placeholders] if part])


class PerSenderDebounceProcessor:
    """Buffers rapid incoming messages and processes one serialized turn per sender."""

    def __init__(
        self,
        *,
        buffer_seconds: float,
        process_turn: Callable[[int, list[str]], Awaitable[None]],
    ) -> None:
        self.buffer_seconds = buffer_seconds
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

    async def _run_sender(self, sender_id: int) -> None:
        while True:
            await asyncio.sleep(self.buffer_seconds)
            async with self._lock:
                messages = self._buffers.pop(sender_id, [])
            if messages:
                await self.process_turn(sender_id, messages)
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
    between_delay: float = 1.5,
    max_chars: int = 400,
) -> None:
    async with client.action(sender_id, SendMessageTypingAction()):
        await asyncio.sleep(initial_delay)
    for message in messages:
        await client.send_message(sender_id, _limit_reply_chars(message, max_chars=max_chars))
        await asyncio.sleep(between_delay)


def _limit_reply_chars(message: str, *, max_chars: int) -> str:
    if len(message) <= max_chars:
        return message
    if max_chars <= 1:
        return "…"[:max_chars]
    return message[: max_chars - 1].rstrip() + "…"


async def run_listener(settings: Settings) -> None:
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
    cleanup_result = repo.cleanup_pii_older_than(retention_days=settings.pii_retention_days)
    if cleanup_result.deleted_messages or cleanup_result.anonymized_orders:
        print(
            "PII retention cleanup: "
            f"deleted_messages={cleanup_result.deleted_messages}, "
            f"anonymized_orders={cleanup_result.anonymized_orders}"
        )

    sender_usernames: dict[int, str | None] = {}

    async def process_customer_turn(sender_id: int, texts: list[str]) -> None:
        username = sender_usernames.get(sender_id)
        db_client = repo.upsert_client(telegram_id=sender_id, username=username)
        for text in texts:
            repo.add_message(client_id=db_client.id, direction="in", text=text)
        recent_db_messages = repo.list_messages(
            client_id=db_client.id,
            limit=settings.conversation_history_limit,
            since_days=settings.conversation_memory_days,
        )
        recent_messages = [
            f"{'Клиент' if message.direction == 'in' else 'Менеджер'}: {message.text}"
            for message in recent_db_messages
        ]
        order_card = await update_active_order_from_messages_with_optional_llm(
            repo,
            settings=settings,
            llm=llm,
            client_id=db_client.id,
            recent_messages=recent_messages,
            company_profile=company_profile,
        )
        stock_date, stock_items = repo.get_latest_daily_stock()
        stock_context = build_stock_context(
            items=stock_items,
            colors=order_card.colors,
            desired_text="\n".join(recent_messages),
            stock_date=stock_date,
        )

        action = await engine.handle_messages(
            client_summary=db_client.summary or "Новый или текущий клиент Telegram.",
            recent_messages=recent_messages,
            stage=db_client.stage,
            stock_context=stock_context,
            order_card=order_card,
        )

        client_label = f"@{username} / {sender_id}" if username else str(sender_id)
        active_order = repo.get_active_order(client_id=db_client.id)
        if active_order and settings.auto_reply_enabled:
            admin_order_text = build_admin_order_request_if_needed(repo, order=active_order, client_label=client_label)
            if admin_order_text:
                await client.send_message(settings.admin_chat_id, admin_order_text)

        if settings.auto_reply_enabled and action.kind in {"human_takeover", "human_review"}:
            await client.send_message(
                settings.admin_chat_id,
                format_admin_notification(
                    title="Нужен ручной контроль",
                    client_label=client_label,
                    stage="new_lead",
                    risk_level=action.risk_level,
                    summary="AI передал диалог человеку.",
                    last_message="\n".join(texts),
                ),
            )

        if settings.auto_reply_enabled:
            await send_typing_and_messages(
                client,
                sender_id=sender_id,
                messages=action.messages,
                initial_delay=settings.min_reply_delay_seconds,
                max_chars=settings.max_reply_chars,
            )
            for message in action.messages:
                repo.add_message(
                    client_id=db_client.id,
                    direction="out",
                    text=_limit_reply_chars(message, max_chars=settings.max_reply_chars),
                )
        else:
            print(f"DRY RUN for {sender_id}: {action.kind} -> {action.messages}")

    debounce_processor = PerSenderDebounceProcessor(
        buffer_seconds=settings.message_buffer_seconds,
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
            ack = handle_stock_command(repo, sender_id=sender_id, text=incoming.text)
            await client.send_message(sender_id, ack)
            return

        sender_usernames[sender_id] = getattr(sender, "username", None)
        await debounce_processor.enqueue(sender_id=sender_id, text=incoming.text)

    await client.start(phone=settings.telegram_phone)
    me = await client.get_me()
    print(f"Listening as id={me.id} phone={me.phone!r}; auto_reply={settings.auto_reply_enabled}")
    await client.run_until_disconnected()


def main() -> None:
    asyncio.run(run_listener(Settings()))


if __name__ == "__main__":
    main()
