from __future__ import annotations

import csv
import io
import re
import secrets
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qs, quote_plus, urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from amelia_manager.company_profile import load_company_profile
from amelia_manager.config import Settings
from amelia_manager.date_formatting import _today_in_timezone, format_human_date
from amelia_manager.db.repository import CatalogItemRecord, ORDER_STATUSES, SQLiteRepository, path_from_sqlite_url
from amelia_manager.events import EventName
from amelia_manager.metrics import calculate_metrics
from amelia_manager.order_card import OrderCard

security = HTTPBasic()
DIALOGUES_PER_PAGE = 50
MESSAGES_PREVIEW_LIMIT = 200
WEB_DIR = Path(__file__).parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


@dataclass
class LoginAttempt:
    failures: deque[datetime]
    blocked_until: datetime | None = None


class LoginRateLimiter:
    def __init__(self, *, max_failures: int = 10, window: timedelta = timedelta(minutes=5), block_for: timedelta = timedelta(minutes=1)) -> None:
        self.max_failures = max_failures
        self.window = window
        self.block_for = block_for
        self._attempts: dict[str, LoginAttempt] = defaultdict(lambda: LoginAttempt(deque()))

    def is_blocked(self, ip: str, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        attempt = self._attempts[ip]
        if attempt.blocked_until and attempt.blocked_until > now:
            return True
        if attempt.blocked_until and attempt.blocked_until <= now:
            attempt.blocked_until = None
        self._prune(attempt, now=now)
        return False

    def record_failure(self, ip: str, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        attempt = self._attempts[ip]
        self._prune(attempt, now=now)
        attempt.failures.append(now)
        if len(attempt.failures) >= self.max_failures:
            attempt.blocked_until = now + self.block_for

    def record_success(self, ip: str) -> None:
        self._attempts.pop(ip, None)

    def _prune(self, attempt: LoginAttempt, *, now: datetime) -> None:
        boundary = now - self.window
        while attempt.failures and attempt.failures[0] < boundary:
            attempt.failures.popleft()


def create_app(*, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    _validate_admin_credentials(settings)
    repo = SQLiteRepository(path_from_sqlite_url(settings.database_url))
    repo.initialize()
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=select_autoescape(["html", "xml"]))
    env.globals.update(
        card_summary=_card_summary,
        card_fields=_card_fields,
        status_info=_status_info,
        status_label=lambda d: _status_info(d)[0],
        order_status_label=_order_status_label,
        order_status_options=lambda: [(status, _order_status_label(status)) for status in ORDER_STATUSES],
        format_time=_format_relative_time,
        format_date_group=_format_date_group,
        metric_percent=_metric_percent,
        metric_number=_metric_number,
        metric_seconds=_metric_seconds,
        funnel_items=_funnel_items,
        metric_delta=_metric_delta,
        risk_label=_risk_label,
        confidence_label=_confidence_label,
    )
    app = FastAPI(title="Amelia Admin")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    limiter = LoginRateLimiter()

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def require_auth(request: Request, credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> None:
        ip = _client_ip_for_rate_limit(request, settings=settings)
        if limiter.is_blocked(ip):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed login attempts")
        ok_user = secrets.compare_digest(credentials.username, settings.admin_username)
        ok_password = secrets.compare_digest(credentials.password, settings.admin_password)
        if not (ok_user and ok_password):
            limiter.record_failure(ip)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
        limiter.record_success(ip)

    def require_same_origin(request: Request) -> None:
        source = request.headers.get("origin") or request.headers.get("referer")
        if not source:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing Origin or Referer")
        parsed = urlparse(source)
        source_host = parsed.netloc.lower()
        request_host = request.headers.get("host", "").lower()
        if not source_host or source_host != request_host:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-site POST rejected")

    def render(template: str, *, status_code: int = 200, **context) -> HTMLResponse:
        return HTMLResponse(env.get_template(template).render(**context), status_code=status_code)

    @app.get("/", response_class=HTMLResponse)
    def index(
        _auth=Depends(require_auth),
        filter: str | None = None,
        active_days: int | None = None,
        q: str = "",
        page: int = 1,
    ):
        page = max(1, page)
        total = repo.count_dialogues(filter_name=filter, active_days=active_days, q=q)
        pages = max(1, -(-total // DIALOGUES_PER_PAGE))
        page = min(page, pages)
        dialogues = repo.list_dialogues(
            filter_name=filter,
            active_days=active_days,
            limit=DIALOGUES_PER_PAGE,
            offset=(page - 1) * DIALOGUES_PER_PAGE,
            q=q,
        )
        return render(
            "dialogues.html",
            nav_active="dialogues",
            title="Диалоги",
            dialogues=dialogues,
            current_filter=filter or "all",
            active_days=active_days,
            q=q,
            page=page,
            pages=pages,
            total=total,
            page_query=_page_query(filter=filter, active_days=active_days, q=q),
        )

    @app.get("/catalog", response_class=HTMLResponse)
    def catalog(_auth=Depends(require_auth), q: str = ""):
        return render("catalog.html", nav_active="catalog", title="Ассортимент", items=repo.list_catalog_items(q=q), q=q)

    @app.post("/catalog/items")
    async def add_catalog_item(request: Request, _auth=Depends(require_auth), _csrf=Depends(require_same_origin)):
        form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
        data = {key: values[-1] for key, values in form.items()}
        try:
            quantity_number = _parse_int_field(data.get("quantity_number", ""), label="Количество")
            price = _parse_int_field(data.get("price", ""), label="Цена")
        except AdminInputError as exc:
            return render(
                "catalog.html",
                status_code=400,
                nav_active="catalog",
                title="Ассортимент",
                items=repo.list_catalog_items(q=""),
                q="",
                error=exc.message,
                form=data,
            )
        item = repo.upsert_catalog_item(
            name=data.get("name", ""),
            quantity_number=quantity_number,
            price=price,
            unit=(data.get("unit", "") or "шт").strip(),
            updated_by=0,
        )
        _record_catalog_update(repo, item_name=item.name, field="created", updated_by="admin")
        return RedirectResponse("/catalog", status_code=303)

    @app.post("/catalog/items/{item_id}/quick")
    async def quick_catalog_update(item_id: int, request: Request, _auth=Depends(require_auth), _csrf=Depends(require_same_origin)):
        item = repo.get_catalog_item(item_id)
        if item is None:
            raise HTTPException(status_code=404)
        payload = await request.json()
        action = str(payload.get("action", ""))
        field = "quantity_number"
        if action == "sold_out":
            updated = repo.update_catalog_item(item_id, quantity_number=0, quantity_text="нет", updated_by=0)
        elif action in {"inc", "dec"}:
            current = item.quantity_number or 0
            delta = 1 if action == "inc" else -1
            value = max(0, current + delta)
            updated = repo.update_catalog_item(item_id, quantity_number=value, updated_by=0)
        elif "quantity_number" in payload:
            try:
                quantity_number = _parse_int_field(str(payload.get("quantity_number", "")), label="Количество")
            except AdminInputError as exc:
                return JSONResponse({"error": exc.message}, status_code=400)
            updated = repo.update_catalog_item(item_id, quantity_number=quantity_number, updated_by=0)
        else:
            raise HTTPException(status_code=400, detail="Unknown catalog action")
        _record_catalog_update(repo, item_name=updated.name, field=field, updated_by="admin")
        return JSONResponse({"item": _catalog_item_payload(updated)})

    @app.get("/catalog/items/{item_id}", response_class=HTMLResponse)
    def catalog_item(item_id: int, _auth=Depends(require_auth)):
        item = repo.get_catalog_item(item_id)
        if item is None:
            raise HTTPException(status_code=404)
        return render("catalog_item.html", nav_active="catalog", title=item.name, item=item)

    @app.post("/catalog/items/{item_id}")
    async def edit_catalog_item(item_id: int, request: Request, _auth=Depends(require_auth), _csrf=Depends(require_same_origin)):
        item = repo.get_catalog_item(item_id)
        if item is None:
            raise HTTPException(status_code=404)
        form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
        data = {key: values[-1] for key, values in form.items()}
        changed = []
        try:
            changes = {
                "name": data.get("name", item.name),
                "quantity_number": _parse_int_field(data.get("quantity_number", ""), label="Количество"),
                "price": _parse_int_field(data.get("price", ""), label="Цена"),
                "unit": (data.get("unit", item.unit or "шт") or "шт").strip(),
                "is_active": data.get("is_active", "1") == "1",
                "updated_by": 0,
            }
        except AdminInputError as exc:
            return render("catalog_item.html", status_code=400, nav_active="catalog", title=item.name, item=item, error=exc.message)
        for field, value in changes.items():
            if field != "updated_by" and getattr(item, field) != value:
                changed.append(field)
        updated = repo.update_catalog_item(item_id, **changes)
        for field in changed:
            _record_catalog_update(repo, item_name=updated.name, field=field, updated_by="admin")
        return RedirectResponse(f"/catalog/items/{updated.id}", status_code=303)

    @app.post("/catalog/items/{item_id}/hide")
    def hide_catalog_item(item_id: int, _auth=Depends(require_auth), _csrf=Depends(require_same_origin)):
        item = repo.get_catalog_item(item_id)
        if item is None:
            raise HTTPException(status_code=404)
        updated = repo.update_catalog_item(item_id, is_active=False, updated_by=0)
        _record_catalog_update(repo, item_name=updated.name, field="is_active", updated_by="admin")
        return RedirectResponse("/catalog", status_code=303)

    @app.get("/clients/{client_id}", response_class=HTMLResponse)
    def client_detail(client_id: int, _auth=Depends(require_auth), all: int = 0):
        client = repo.get_client_by_id(client_id)
        if client is None:
            raise HTTPException(status_code=404)
        total_messages = repo.count_messages(client_id=client.id)
        show_all = bool(all)
        limit = total_messages if show_all else MESSAGES_PREVIEW_LIMIT
        return render(
            "dialogue.html",
            nav_active="dialogues",
            title="Диалог",
            client=client,
            messages=repo.list_messages(client_id=client.id, limit=max(limit, 1)),
            order=repo.get_active_order(client_id=client.id),
            total_messages=total_messages,
            shown_messages=min(limit, total_messages),
            show_all=show_all,
        )

    @app.post("/clients/{client_id}/pause")
    def pause(client_id: int, _auth=Depends(require_auth), _csrf=Depends(require_same_origin)):
        client = repo.get_client_by_id(client_id)
        if client is None:
            raise HTTPException(status_code=404)
        repo.pause_client(client_id=client.id, paused_by="admin", reason="manual")
        return RedirectResponse(f"/clients/{client.id}", status_code=303)

    @app.post("/clients/{client_id}/resume")
    def resume(client_id: int, _auth=Depends(require_auth), _csrf=Depends(require_same_origin)):
        client = repo.get_client_by_id(client_id)
        if client is None:
            raise HTTPException(status_code=404)
        repo.resume_client(client_id=client.id, reason="manual")
        return RedirectResponse(f"/clients/{client.id}", status_code=303)

    @app.post("/clients/{client_id}/card")
    async def edit_card(client_id: int, request: Request, _auth=Depends(require_auth), _csrf=Depends(require_same_origin)):
        client = repo.get_client_by_id(client_id)
        order = repo.get_active_order(client_id=client_id)
        if client is None or order is None:
            raise HTTPException(status_code=404)
        form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
        try:
            patch = _card_patch({key: values[-1] for key, values in form.items()})
        except AdminInputError as exc:
            total_messages = repo.count_messages(client_id=client.id)
            return render(
                "dialogue.html",
                status_code=400,
                nav_active="dialogues",
                title="Диалог",
                client=client,
                messages=repo.list_messages(client_id=client.id, limit=MESSAGES_PREVIEW_LIMIT),
                order=order,
                total_messages=total_messages,
                shown_messages=min(MESSAGES_PREVIEW_LIMIT, total_messages),
                show_all=False,
                error=exc.message,
            )
        updated = _apply_card_patch(order.card, patch)
        repo.update_order_card(order_id=order.id, card=updated)
        changed = [key for key in patch if getattr(order.card, key) != getattr(updated, key)]
        if changed:
            repo.record_event(client_id=client.id, order_id=order.id, event=EventName.CARD_EDITED_MANUALLY, payload={"fields": changed})
        return RedirectResponse(f"/clients/{client.id}", status_code=303)

    @app.post("/clients/{client_id}/orders/{order_id}/status")
    async def change_order_status(client_id: int, order_id: int, request: Request, _auth=Depends(require_auth), _csrf=Depends(require_same_origin)):
        client = repo.get_client_by_id(client_id)
        order = repo.get_order_by_id(order_id)
        if client is None or order is None or order.client_id != client.id:
            raise HTTPException(status_code=404)
        form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
        status_value = (form.get("status") or [""])[-1]
        try:
            repo.update_order_status(order_id=order.id, status=status_value, changed_by="admin")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(f"/clients/{client.id}", status_code=303)

    @app.get("/metrics", response_class=HTMLResponse)
    def metrics(days: int = 7, date_from: str | None = None, date_to: str | None = None, _auth=Depends(require_auth)):
        start, end, label = _metric_period(settings, days=days, date_from=date_from, date_to=date_to)
        report = calculate_metrics(repo, date_from=start, date_to=end)
        previous = calculate_metrics(repo, date_from=start - (end - start) - timedelta(days=1), date_to=start - timedelta(days=1))
        return render("metrics.html", nav_active="metrics", title="Метрики", days=days, period_label=label, date_from=start, date_to=end, metrics=report, previous=previous)

    @app.get("/metrics.csv")
    def metrics_csv(days: int = 7, date_from: str | None = None, date_to: str | None = None, _auth=Depends(require_auth)):
        start, end, _label = _metric_period(settings, days=days, date_from=date_from, date_to=date_to)
        report = calculate_metrics(repo, date_from=start, date_to=end)
        return StreamingResponse(
            io.StringIO(_metrics_csv(report)),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=amelia-metrics.csv"},
        )

    return app


def _validate_admin_credentials(settings: Settings) -> None:
    if not settings.admin_username.strip() or not settings.admin_password.strip() or (settings.admin_username == "admin" and settings.admin_password == "admin"):
        raise RuntimeError("Set ADMIN_USERNAME and ADMIN_PASSWORD in .env before starting admin UI; default or empty credentials are forbidden")


def _client_ip_for_rate_limit(request: Request, *, settings: Settings) -> str:
    peer_ip = request.client.host if request.client else "unknown"
    trusted_proxy_ips = settings.trusted_proxy_ips
    if peer_ip not in trusted_proxy_ips:
        return peer_ip
    forwarded_for = request.headers.get("x-forwarded-for", "")
    for raw_ip in reversed(forwarded_for.split(",")):
        ip = raw_ip.strip()
        if ip and ip not in trusted_proxy_ips:
            return ip
    return peer_ip


class AdminInputError(ValueError):
    """Invalid value in an admin form: shown to the user instead of being guessed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


_SPACES_RE = re.compile(r"[\s  ]")
_CURRENCY_SUFFIX_RE = re.compile(r"(?:₽|руб(?:\.|лей)?|р\.)$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(-?\d+)(?:[.](\d+))?")


def _parse_int_field(value: str | None, *, label: str, minimum: int | None = 0) -> int | None:
    """Parse an integer form field, refusing to guess at anything unexpected.

    The old implementation kept only digits, so "12.50" silently became 1250 and a
    price could be off by a factor of a hundred. Now anything ambiguous is an error.
    """
    raw = _SPACES_RE.sub("", str(value or ""))
    raw = _CURRENCY_SUFFIX_RE.sub("", raw)
    if not raw:
        return None
    match = _NUMBER_RE.fullmatch(raw.replace(",", "."))
    if not match:
        raise AdminInputError(f"{label}: нужно число, а получено «{value}»")
    if match.group(2) and int(match.group(2)) != 0:
        raise AdminInputError(f"{label}: дробные значения не поддерживаются, введите целое число")
    result = int(match.group(1))
    if minimum is not None and result < minimum:
        raise AdminInputError(f"{label}: значение не может быть меньше {minimum}")
    return result


def _catalog_item_payload(item: CatalogItemRecord) -> dict[str, object]:
    return {
        "id": item.id,
        "name": item.name,
        "status": item.status.value,
        "quantity_text": item.quantity_text,
        "quantity_number": item.quantity_number,
        "price": item.price,
        "unit": item.unit,
        "is_active": item.is_active,
        "updated_at": item.updated_at,
    }


def _record_catalog_update(repo: SQLiteRepository, *, item_name: str, field: str, updated_by: str) -> None:
    system = repo.upsert_client(telegram_id=0, username="admin")
    repo.record_event(
        client_id=system.id,
        order_id=None,
        event=EventName.CATALOG_UPDATED,
        payload={"item_name": item_name, "field": field, "updated_by": updated_by},
    )


def _page_query(*, filter: str | None, active_days: int | None, q: str) -> str:
    """Query string that keeps filters when moving between pages."""
    parts = []
    if filter:
        parts.append(f"filter={quote_plus(filter)}")
    if active_days is not None:
        parts.append(f"active_days={active_days}")
    if q.strip():
        parts.append(f"q={quote_plus(q.strip())}")
    return ("&" + "&".join(parts)) if parts else ""


def _card_patch(form: dict[str, str]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    text_fields = [
        "fulfillment_type",
        "delivery_date",
        "delivery_time",
        "address",
        "sender_name",
        "sender_phone",
        "recipient_name",
        "recipient_phone",
        "postcard_text",
        "payment_method",
    ]
    for field in text_fields:
        if field in form:
            value = form[field].strip()
            patch[field] = value or None
    if "budget" in form:
        patch["budget"] = _parse_int_field(form["budget"], label="Бюджет")
    if "colors" in form:
        patch["colors"] = [item.strip() for item in form.get("colors", "").split(",") if item.strip()]
    return patch


def _apply_card_patch(card: OrderCard, patch: dict[str, Any]) -> OrderCard:
    allowed = set(OrderCard.__dataclass_fields__.keys()) - {"admin_request_sent", "client_summary_sent"}
    cleaned = {key: value for key, value in patch.items() if key in allowed}
    return OrderCard.from_dict({**card.to_dict(), **cleaned})


def _card_fields(card: OrderCard) -> list[tuple[str, str, object]]:
    return [
        ("occasion", "Повод", card.occasion),
        ("budget", "Бюджет", card.budget),
        ("colors", "Пожелания / цвета", ", ".join(card.colors)),
        ("forbidden_flowers", "Исключить", ", ".join(card.forbidden_flowers)),
        ("fulfillment_type", "Формат", card.fulfillment_type),
        ("delivery_date", "Дата", card.delivery_date),
        ("delivery_time", "Время", card.delivery_time),
        ("address", "Адрес", card.address),
        ("sender_name", "Имя клиента/отправителя", card.sender_name),
        ("sender_phone", "Телефон клиента/отправителя", card.sender_phone),
        ("recipient_name", "Имя получателя", card.recipient_name),
        ("recipient_phone", "Телефон получателя", card.recipient_phone),
        ("payment_method", "Оплата", card.payment_method),
        ("postcard_text", "Текст открытки", card.postcard_text),
        ("anonymous", "Анонимно", _bool_label(card.anonymous)),
        ("photo_report_requested", "Фотоотчёт", _bool_label(card.photo_report_requested)),
        ("admin_request_sent", "Заявка отправлена", _bool_label(card.admin_request_sent)),
    ]


def _card_summary(card: OrderCard) -> str:
    parts = []
    for _code, label, value in _card_fields(card):
        if value not in (None, "", [], {}):
            parts.append(f"{label}: {value}")
    return "\n".join(parts) if parts else "Карточка пустая"


def _order_status_label(status: str) -> str:
    return {
        "active": "В работе",
        "draft": "Черновик",
        "submitted": "Заявка отправлена",
        "confirmed": "Подтверждён",
        "in_production": "В работе у флориста",
        "ready": "Готов",
        "fulfilled": "Выполнен",
        "cancelled": "Отменён",
    }.get(status, status)


def _metric_delta(current: object, previous: object, *, higher_is_better: bool = True) -> dict[str, str] | None:
    """Change against the previous period, already computed but never shown before."""
    try:
        current_value = float(current)  # type: ignore[arg-type]
        previous_value = float(previous)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if previous_value == 0:
        return None
    change = (current_value - previous_value) / previous_value * 100
    if abs(change) < 1:
        return {"text": "без изменений", "kind": ""}
    grew = change > 0
    return {
        "text": f"{'↑' if grew else '↓'} {abs(change):.0f}%",
        "kind": "good" if grew == higher_is_better else "bad",
    }


def _status_info(dialogue) -> tuple[str, str]:
    if dialogue.client.opted_out_at:
        return "отписался", "muted"
    if dialogue.client.bot_paused_at:
        return "на паузе", "danger"
    if dialogue.active_order:
        if dialogue.active_order.status in {"fulfilled", "cancelled"}:
            return _order_status_label(dialogue.active_order.status), "muted"
        if dialogue.active_order.status in {"submitted", "confirmed", "in_production", "ready"}:
            return _order_status_label(dialogue.active_order.status), "success"
    if dialogue.active_order and dialogue.active_order.card.admin_request_sent:
        return "заявка отправлена", "success"
    return "в работе", "neutral"


def _format_relative_time(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    now = datetime.now(parsed.tzinfo) if parsed.tzinfo is not None else datetime.now(UTC).replace(tzinfo=None)
    delta = now - parsed
    if timedelta(0) <= delta < timedelta(minutes=1):
        return "только что"
    if timedelta(minutes=1) <= delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)} минут назад"
    if timedelta(hours=1) <= delta < timedelta(days=1):
        return f"{int(delta.total_seconds() // 3600)} часов назад"
    if delta.days == 1:
        return "вчера " + parsed.strftime("%H:%M")
    return parsed.strftime("%d.%m.%Y %H:%M")


def _format_date_group(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:10]
    return format_human_date(parsed.date().isoformat())


def _metric_period(settings: Settings, *, days: int, date_from: str | None, date_to: str | None) -> tuple[date, date, str]:
    today = _today_in_timezone(load_company_profile(settings.company_profile_name).timezone_name)
    if date_from and date_to:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
        return start, end, f"{start.isoformat()} — {end.isoformat()}"
    days = days if days in {7, 30, 90} else 7
    start = today - timedelta(days=days - 1)
    return start, today, f"{days} дней"


def _funnel_items(metrics: dict[str, Any]) -> list[tuple[str, int, float]]:
    funnel = metrics.get("funnel", {})
    total = metrics.get("conversion", {}).get("dialogs", 0) or max(funnel.values(), default=0)
    order = ["product_preferences", "budget", "date", "time", "fulfillment_type", "delivery_address", "recipient_name", "recipient_phone", "customer_name", "customer_phone", "payment_method"]
    labels = {
        "product_preferences": "Пожелания",
        "budget": "Бюджет",
        "date": "Дата",
        "time": "Время",
        "fulfillment_type": "Формат",
        "delivery_address": "Адрес доставки",
        "recipient_name": "Имя получателя",
        "recipient_phone": "Телефон получателя",
        "customer_name": "Имя клиента",
        "customer_phone": "Телефон клиента",
        "payment_method": "Оплата",
    }
    keys = [key for key in order if key in funnel] + sorted(key for key in funnel if key not in order)
    return [(labels.get(key, key), int(funnel[key]), _rate_percent(int(funnel[key]), int(total))) for key in keys]


def _metric_percent(value: float | None) -> str:
    return f"{(value or 0) * 100:.1f}%"


def _metric_number(value: float | int | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}"
    return str(int(value))


def _metric_seconds(value: float | int | None) -> str:
    if value is None:
        return "—"
    if value < 60:
        return f"{value:.0f} сек"
    return f"{value / 60:.1f} мин"


def _risk_label(value: str) -> str:
    labels = {
        "guarantee_request": "Просьба гарантии",
        "complaint": "Жалоба",
        "price": "Цена",
        "unknown": "Другое",
    }
    return labels.get(value, value)


def _confidence_label(value: str) -> str:
    return {"0-0.5": "Низкая", "0.5-0.7": "Средняя", "0.7-1.0": "Высокая"}.get(value, value)


def _metrics_csv(report: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "metric", "value"])
    for section, value in report.items():
        _write_metric_rows(writer, section, value)
    return output.getvalue()


def _write_metric_rows(writer: csv.writer, prefix: str, value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _write_metric_rows(writer, f"{prefix},{key}", nested)
    else:
        section, _, metric = prefix.partition(",")
        writer.writerow([section, metric or section, value])


def _rate_percent(value: int, total: int) -> float:
    return round(value / total * 100, 1) if total else 0.0


def _bool_label(value: bool | None) -> str:
    if value is True:
        return "да"
    if value is False:
        return "нет"
    return ""


app = create_app()
