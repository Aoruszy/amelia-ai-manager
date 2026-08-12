from __future__ import annotations

import secrets
from datetime import date, timedelta
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jinja2 import DictLoader, Environment, select_autoescape

from amelia_manager.company_profile import load_company_profile
from amelia_manager.config import Settings
from amelia_manager.date_formatting import _today_in_timezone
from amelia_manager.db.repository import SQLiteRepository, path_from_sqlite_url
from amelia_manager.events import EventName
from amelia_manager.metrics import calculate_metrics
from amelia_manager.order_card import OrderCard, merge_order_patch

security = HTTPBasic()

TEMPLATES = {
    "base.html": """
<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>{{ title }}</title>
<style>body{font-family:sans-serif;max-width:1100px;margin:24px auto;padding:0 16px}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:8px;text-align:left}.in{background:#eef}.out{background:#efe}.admin{background:#fee}.card{white-space:pre-wrap}.actions form{display:inline}</style>
</head><body><nav><a href="/">Диалоги</a> · <a href="/metrics">Метрики</a></nav><hr>{% block body %}{% endblock %}</body></html>
""",
    "index.html": """{% extends 'base.html' %}{% block body %}<h1>Диалоги</h1>
<p><a href="/?filter=paused">Только на паузе</a> · <a href="/?filter=ready">Готовые заявки</a> · <a href="/?active_days=7">Активные 7 дней</a></p>
<table><tr><th>Клиент</th><th>Стадия</th><th>Статус</th><th>Последнее сообщение</th><th>Карточка</th></tr>
{% for d in dialogues %}<tr><td><a href="/clients/{{ d.client.id }}">{{ d.client.username or ('client #' ~ d.client.id) }}</a></td><td>{{ d.client.stage }}</td><td>{{ status_label(d) }}</td><td>{{ d.last_message_at or '' }}</td><td>{{ card_summary(d.active_order.card) if d.active_order else '' }}</td></tr>{% endfor %}</table>{% endblock %}""",
    "client.html": """{% extends 'base.html' %}{% block body %}<h1>Диалог {{ client.username or ('client #' ~ client.id) }}</h1>
<div class="actions">{% if client.bot_paused_at %}<form method="post" action="/clients/{{ client.id }}/resume"><button>Вернуть боту</button></form>{% else %}<form method="post" action="/clients/{{ client.id }}/pause"><button>Перехватить</button></form>{% endif %}</div>
<h2>Переписка</h2>{% for m in messages %}<div class="{{ m.direction }}"><b>{{ m.direction }}</b> {{ m.created_at }}<br>{{ m.text }}</div>{% endfor %}
<h2>Карточка заказа</h2>{% if order %}<div class="card">{{ card_summary(order.card) }}</div><form method="post" action="/clients/{{ client.id }}/card">
<p>Бюджет <input name="budget" value="{{ order.card.budget or '' }}"></p><p>Формат <input name="fulfillment_type" value="{{ order.card.fulfillment_type or '' }}"></p><p>Цвета <input name="colors" value="{{ ', '.join(order.card.colors) }}"></p><p>Дата <input name="delivery_date" value="{{ order.card.delivery_date or '' }}"></p><p>Время <input name="delivery_time" value="{{ order.card.delivery_time or '' }}"></p><p>Адрес <input name="address" value="{{ order.card.address or '' }}"></p><button>Сохранить карточку</button></form>{% else %}<p>Активной карточки нет.</p>{% endif %}{% endblock %}""",
    "metrics.html": """{% extends 'base.html' %}{% block body %}<h1>Метрики за {{ days }} дней</h1><h2>Воронка</h2><table><tr><th>Шаг</th><th>Количество</th></tr>{% for k,v in metrics.funnel.items() %}<tr><td>{{ k }}</td><td>{{ v }}</td></tr>{% endfor %}</table><h2>Конверсия</h2><p>{{ metrics.conversion.rate|round(2) }} — {{ metrics.conversion.admin_requests }} из {{ metrics.conversion.dialogs }}</p><h2>Confidence</h2><p>{{ metrics.quality.confidence_distribution }}</p><h2>Операции</h2><p>off-hours: {{ metrics.ops.off_hours_rate|round(2) }}</p>{% endblock %}""",
}


def create_app(*, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    repo = SQLiteRepository(path_from_sqlite_url(settings.database_url))
    repo.initialize()
    env = Environment(loader=DictLoader(TEMPLATES), autoescape=select_autoescape(["html", "xml"]))
    env.globals["card_summary"] = _card_summary
    env.globals["status_label"] = _status_label
    app = FastAPI(title="Amelia Admin")

    def require_auth(credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> None:
        ok_user = secrets.compare_digest(credentials.username, settings.admin_username)
        ok_password = secrets.compare_digest(credentials.password, settings.admin_password)
        if not (ok_user and ok_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})

    def render(template: str, **context) -> HTMLResponse:
        return HTMLResponse(env.get_template(template).render(**context))

    @app.get("/", response_class=HTMLResponse)
    def index(_auth=Depends(require_auth), filter: str | None = None, active_days: int | None = None):
        return render("index.html", title="Диалоги", dialogues=repo.list_dialogues(filter_name=filter, active_days=active_days, limit=200))

    @app.get("/clients/{client_id}", response_class=HTMLResponse)
    def client_detail(client_id: int, _auth=Depends(require_auth)):
        client = repo.get_client_by_id(client_id)
        if client is None:
            raise HTTPException(status_code=404)
        return render(
            "client.html",
            title="Диалог",
            client=client,
            messages=repo.list_messages(client_id=client.id, limit=1000),
            order=repo.get_active_order(client_id=client.id),
        )

    @app.post("/clients/{client_id}/pause")
    def pause(client_id: int, _auth=Depends(require_auth)):
        client = repo.get_client_by_id(client_id)
        if client is None:
            raise HTTPException(status_code=404)
        repo.pause_client(client_id=client.id, paused_by="admin", reason="manual")
        return RedirectResponse(f"/clients/{client.id}", status_code=303)

    @app.post("/clients/{client_id}/resume")
    def resume(client_id: int, _auth=Depends(require_auth)):
        client = repo.get_client_by_id(client_id)
        if client is None:
            raise HTTPException(status_code=404)
        repo.resume_client(client_id=client.id, reason="manual")
        return RedirectResponse(f"/clients/{client.id}", status_code=303)

    @app.post("/clients/{client_id}/card")
    async def edit_card(client_id: int, request: Request, _auth=Depends(require_auth)):
        client = repo.get_client_by_id(client_id)
        order = repo.get_active_order(client_id=client_id)
        if client is None or order is None:
            raise HTTPException(status_code=404)
        form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
        patch = _card_patch({key: values[-1] for key, values in form.items()})
        updated = merge_order_patch(order.card, patch)
        repo.update_order_card(order_id=order.id, card=updated)
        changed = [key for key in patch if getattr(order.card, key) != getattr(updated, key)]
        if changed:
            repo.record_event(client_id=client.id, order_id=order.id, event=EventName.CARD_EDITED_MANUALLY, payload={"fields": changed})
        return RedirectResponse(f"/clients/{client.id}", status_code=303)

    @app.get("/metrics", response_class=HTMLResponse)
    def metrics(days: int = 7, _auth=Depends(require_auth)):
        days = days if days in {7, 30, 90} else 7
        today = _today_in_timezone(load_company_profile(settings.company_profile_name).timezone_name)
        start = today - timedelta(days=days - 1)
        report = calculate_metrics(repo, date_from=start, date_to=today)
        return render("metrics.html", title="Метрики", days=days, metrics=report)

    return app


def _card_patch(form: dict[str, str]) -> dict:
    patch: dict[str, object] = {}
    for field in ["fulfillment_type", "delivery_date", "delivery_time", "address"]:
        value = form.get(field, "").strip()
        if value:
            patch[field] = value
    budget = form.get("budget", "").strip()
    if budget:
        patch["budget"] = int(budget)
    colors = [item.strip() for item in form.get("colors", "").split(",") if item.strip()]
    if colors:
        patch["colors"] = colors
    return patch


def _card_summary(card: OrderCard) -> str:
    parts = []
    for label, value in [
        ("Бюджет", card.budget),
        ("Формат", card.fulfillment_type),
        ("Цвета", ", ".join(card.colors)),
        ("Дата", card.delivery_date),
        ("Время", card.delivery_time),
        ("Адрес", card.address),
    ]:
        if value:
            parts.append(f"{label}: {value}")
    return "\n".join(parts) if parts else "Карточка пустая"


def _status_label(dialogue) -> str:
    if dialogue.client.bot_paused_at:
        return "на паузе"
    if dialogue.active_order and dialogue.active_order.card.admin_request_sent:
        return "заявка отправлена"
    return "активен"


app = create_app()
