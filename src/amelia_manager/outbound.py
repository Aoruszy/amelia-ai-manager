from __future__ import annotations

import logging
import json
import re
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.config import Settings
from amelia_manager.date_formatting import format_human_date
from amelia_manager.db.repository import ClientRecord, OrderRecord, SQLiteRepository
from amelia_manager.events import EventName
from amelia_manager.order_card import OrderCard

LOGGER = logging.getLogger(__name__)


class OutboundKind(StrEnum):
    FOLLOWUP_1 = "followup_1"
    FOLLOWUP_2 = "followup_2"
    ORDER_REMINDER = "order_reminder"
    ORDER_CONFIRMED = "order_confirmed"
    ORDER_READY = "order_ready"


_OPT_OUT_RE = re.compile(r"\b(не\s+пишите|отстаньте|не\s+беспоко(?:ить|йте)|хватит\s+писать|отпишите)\b", re.IGNORECASE)
_STATUS_RE = re.compile(
    r"\b(что\s+(там\s+)?с\s+моим\s+заказом|когда\s+привезут|заказ\s+готов|статус\s+заказа|где\s+мой\s+букет|как\s+там\s+заказ)\b",
    re.IGNORECASE,
)
_ORDER_CONTEXT_RE = re.compile(r"\b(доставк\w*|сам\s+заберу|самовывоз|цвет\w*|букет|открытк\w*|адрес|время|дат\w*)\b", re.IGNORECASE)


def is_opt_out_text(text: str) -> bool:
    normalized = " ".join((text or "").strip().split())
    if not normalized or len(normalized.split()) > 6 or _ORDER_CONTEXT_RE.search(normalized):
        return False
    return bool(_OPT_OUT_RE.search(normalized))


def is_order_status_question(text: str) -> bool:
    return bool(_STATUS_RE.search(text or ""))


def build_order_status_reply(repo: SQLiteRepository, *, client_id: int, company_profile: CompanyProfile) -> str:
    order = repo.get_active_order(client_id=client_id)
    if order is None:
        return "Активного заказа у меня пока нет. Можем оформить: подскажите, какой букет нужен?"
    card = order.card
    parts = []
    if card.delivery_date:
        parts.append(f"дата: {format_human_date(card.delivery_date, timezone_name=company_profile.timezone_name)}")
    if card.delivery_time:
        parts.append(f"время: {card.delivery_time}")
    if card.fulfillment_type:
        parts.append(f"формат: {_format_fulfillment(card.fulfillment_type)}")
    status = _order_status_label(order.status)
    details = ", ".join(parts) if parts else "детали ещё уточняются"
    return f"По заказу вижу: {details}. Текущий статус: {status}. Фактическое выполнение подтвердит менеджер."


def _order_status_label(status: str) -> str:
    return {
        "active": "заказ ещё оформляется",
        "draft": "заказ ещё оформляется",
        "submitted": "заявка передана менеджеру",
        "confirmed": "заказ подтверждён",
        "in_production": "заказ в работе",
        "ready": "заказ готов",
        "fulfilled": "заказ выполнен",
        "cancelled": "заказ отменён",
    }.get(status, status)


def schedule_followups_after_reply(
    repo: SQLiteRepository,
    *,
    client: ClientRecord,
    order: OrderRecord | None,
    inbound_count: int,
    action_kind: str,
    now: datetime,
    company_profile: CompanyProfile | None = None,
) -> int:
    if order is None or client.opted_out_at or client.bot_paused_at:
        return 0
    if inbound_count <= 1 or action_kind in {"human_takeover", "human_review"}:
        return 0
    if order.card.admin_request_sent or order.card.is_ready_for_admin_request():
        return 0
    step_code = _next_step_code(order.card)
    scheduled = 0
    for kind, delay in ((OutboundKind.FOLLOWUP_1, timedelta(hours=24)), (OutboundKind.FOLLOWUP_2, timedelta(hours=72))):
        if repo.has_outbound(order_id=order.id, kind=kind):
            continue
        record = repo.schedule_outbound(client_id=client.id, order_id=order.id, kind=kind, scheduled_at=now + delay)
        repo.record_event(client_id=client.id, order_id=order.id, event=EventName.FOLLOWUP_SCHEDULED, payload={"kind": kind.value, "step_code": step_code}, created_at=now)
        scheduled += 1 if record.created_at else 0
    return scheduled


def schedule_order_reminders(repo: SQLiteRepository, *, now: datetime, company_profile: CompanyProfile) -> int:
    target_date = (now + timedelta(days=1)).date().isoformat()
    scheduled = 0
    for order, client in repo.list_active_orders_with_clients():
        if not order.card.admin_request_sent or order.card.delivery_date != target_date:
            continue
        if repo.has_outbound(order_id=order.id, kind=OutboundKind.ORDER_REMINDER):
            continue
        repo.schedule_outbound(client_id=client.id, order_id=order.id, kind=OutboundKind.ORDER_REMINDER, scheduled_at=now)
        scheduled += 1
    return scheduled


async def send_workload_warnings(telegram_client, *, repo: SQLiteRepository, settings: Settings, now: datetime) -> int:
    if settings.workload_warning_threshold <= 0 or settings.admin_chat_id is None:
        return 0
    date_from = now.date()
    date_to = date_from + timedelta(days=settings.workload_horizon_days - 1)
    rows = repo.list_workload_orders(date_from=date_from, date_to=date_to)
    by_date: dict[str, list[OrderRecord]] = {}
    for row in rows:
        if row.order.card.delivery_date:
            by_date.setdefault(row.order.card.delivery_date, []).append(row.order)
    sent = 0
    for day, orders in sorted(by_date.items()):
        total = len(orders)
        if total <= settings.workload_warning_threshold:
            continue
        previous = _last_workload_warning_count(repo, day)
        if previous is not None and total < previous + settings.workload_warning_repeat_growth:
            continue
        delivery = sum(1 for order in orders if order.card.fulfillment_type == "delivery")
        pickup = sum(1 for order in orders if order.card.fulfillment_type == "pickup")
        profile = load_company_profile(settings.company_profile_name)
        text = profile.workload_warning_template.format(date=day, total=total, delivery=delivery, pickup=pickup)
        try:
            await telegram_client.send_message(settings.admin_chat_id, text)
        except Exception:  # noqa: BLE001 - scheduler tick must survive Telegram failures
            LOGGER.exception("workload_warning_send_failed", extra={"event": "workload_warning_send_failed", "payload": {"date": day, "count": total}})
            continue
        system = repo.upsert_client(telegram_id=0, username="system")
        repo.record_event(
            client_id=system.id,
            order_id=None,
            event=EventName.WORKLOAD_WARNING_SENT,
            payload={"date": day, "count": total, "delivery": delivery, "pickup": pickup},
            created_at=now,
        )
        sent += 1
    return sent


def _last_workload_warning_count(repo: SQLiteRepository, day: str) -> int | None:
    for event in reversed(repo.list_events(event=EventName.WORKLOAD_WARNING_SENT)):
        try:
            payload = json.loads(event.payload_json or "{}")
        except Exception:  # noqa: BLE001 - ignore malformed historical payloads
            continue
        if payload.get("date") == day:
            try:
                return int(payload.get("count"))
            except (TypeError, ValueError):
                return None
    return None


async def process_outbound_tick(
    telegram_client,
    *,
    repo: SQLiteRepository,
    settings: Settings,
    company_profile: CompanyProfile,
    now: datetime,
    active_buffers: set[int],
    llm_client=None,
) -> None:
    try:
        await send_workload_warnings(telegram_client, repo=repo, settings=settings, now=now)
        schedule_order_reminders(repo, now=now, company_profile=company_profile)
        due = repo.list_due_outbound(now=now)
        for item in due:
            client = repo.get_client_by_id(item.client_id)
            if client is None:
                continue
            if client.id in active_buffers:
                continue
            if item.kind in {OutboundKind.FOLLOWUP_1.value, OutboundKind.FOLLOWUP_2.value} and (client.opted_out_at or client.bot_paused_at):
                continue
            if not _within_work_hours(now, settings=settings):
                repo.reschedule_outbound(item.id, scheduled_at=_next_work_start(now, company_profile.timezone_name, settings=settings))
                continue
            order = repo.get_order_by_id(item.order_id) if item.order_id is not None else None
            text = await build_outbound_text(item.kind, order.card if order else OrderCard(), company_profile, llm_client=llm_client)
            try:
                await telegram_client.send_message(client.telegram_id, text)
            except Exception:  # noqa: BLE001 - retry next tick without breaking incoming listener
                failed = repo.increment_outbound_attempt(item.id, now=now)
                if failed.cancelled_at:
                    repo.record_event(client_id=client.id, order_id=item.order_id, event=EventName.FOLLOWUP_CANCELLED, payload={"kind": item.kind, "reason": "send_failed"}, created_at=now)
                LOGGER.exception("outbound_send_failed", extra={"event": "outbound_send_failed", "client_id": client.id, "order_id": item.order_id, "payload": {"kind": item.kind}})
                continue
            repo.mark_outbound_sent(item.id, sent_at=now)
            if item.kind == OutboundKind.ORDER_REMINDER.value:
                repo.record_event(client_id=client.id, order_id=item.order_id, event=EventName.REMINDER_SENT, payload={}, created_at=now)
            else:
                repo.record_event(client_id=client.id, order_id=item.order_id, event=EventName.FOLLOWUP_SENT, payload={"kind": item.kind, "step_code": _next_step_code(order.card if order else OrderCard())}, created_at=now)
    except Exception:  # noqa: BLE001 - scheduler isolation
        LOGGER.exception("outbound_tick_failed", extra={"event": "outbound_tick_failed", "payload": {}})


async def build_outbound_text(kind: str, card: OrderCard, profile: CompanyProfile, *, llm_client=None) -> str:
    if kind == OutboundKind.ORDER_REMINDER.value:
        details = ", ".join(part for part in [card.delivery_date, card.delivery_time, _format_fulfillment(card.fulfillment_type)] if part)
        return f"{profile.order_reminder_fallback} Детали: {details}."
    if kind == OutboundKind.ORDER_CONFIRMED.value:
        return "Ваш заказ подтвердили. Если что-то изменится — напишите, пожалуйста."
    if kind == OutboundKind.ORDER_READY.value:
        return "Ваш заказ готов. Можно забирать или ожидать доставку по согласованным деталям."
    step = _next_step_code(card)
    fallback = profile.followup_fallbacks.get(step) or profile.followup_fallbacks.get("default") or "Если заказ ещё актуален, напишите — продолжим. Можно не отвечать, если уже неактуально."
    if llm_client is None:
        return fallback
    prompt = (
        f"Ты менеджер {profile.company_name}. Клиент не отвечает 24+ часа. "
        f"next_step_instruction: мягко вернись к шагу {step}. "
        "Напиши одно короткое сообщение без давления, без скидок, с фразой что можно не отвечать. "
        f"Фолбэк-ориентир: {fallback}"
    )
    try:
        text = (await llm_client.generate(prompt)).strip()
    except Exception:  # noqa: BLE001 - fallback is required when LLM unavailable
        return fallback
    return text[:400] if text else fallback


def _next_step_code(card: OrderCard) -> str:
    if not card.budget:
        return "budget"
    if not card.fulfillment_type:
        return "format"
    if card.fulfillment_type == "delivery" and not card.address:
        return "address"
    return "default"


def _format_fulfillment(value: str | None) -> str:
    return {"delivery": "доставка", "pickup": "самовывоз"}.get(value or "", value or "не указан")


def _within_work_hours(now: datetime, *, settings: Settings) -> bool:
    current = now.timetz().replace(tzinfo=None) if now.tzinfo else now.time()
    return _parse_hhmm(settings.work_hours_start) <= current <= _parse_hhmm(settings.work_hours_end)


def _next_work_start(now: datetime, timezone_name: str, settings: Settings | None = None) -> datetime:
    local = now.astimezone(ZoneInfo(timezone_name)) if now.tzinfo else now.replace(tzinfo=ZoneInfo(timezone_name))
    start = _parse_hhmm((settings or Settings()).work_hours_start)
    candidate = local.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    if local.time() >= start:
        candidate += timedelta(days=1)
    return candidate


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))
