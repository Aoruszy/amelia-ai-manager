# Universal AI Manager / Amelia profile

AI Telegram manager core with a first company profile for Amelia Flowers.

## MVP defaults

- Telegram user account via Telethon.
- Manager persona: Алина.
- Company profile: `COMPANY_PROFILE_NAME=amelia_flowers`.
- Admin notifications in Telegram via `ADMIN_CHAT_ID`.
- Auto-reply can be enabled for everyone who writes to the account.
- Current LLM target: OpenAI Responses API by default (`LLM_PROVIDER=openai`); Gemini remains supported through `LLM_PROVIDER=gemini`.

## Setup

```bash
uv sync --extra dev
cp .env.example .env
# fill TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, ADMIN_CHAT_ID, LLM_API_KEY
# fill ADMIN_USERNAME and ADMIN_PASSWORD before starting admin UI
uv run pytest -q
uv run python -m amelia_manager.telegram_runtime
```

## Measurement reports

Keep only the declared baseline report and the latest eval run in `reports/`: today that means `eval_baseline_after_review.json` and the current `eval_round*.json`. When committing a new eval run, remove the previous round report in the same commit; change the baseline only by an explicit decision, never automatically. Do not add `reports/` to `.gitignore` because prompt/model changes are reviewed against committed eval output.

## Admin UI

The admin UI is a separate FastAPI app. It is protected with Basic Auth, rate-limits failed logins in memory, and refuses to start with empty/default admin credentials. Basic Auth sends credentials as base64, not encryption, so expose the panel only behind a TLS terminator such as Cloudflare Tunnel or Caddy; never publish it over plain HTTP.

All logged-in users have the same access level: dialogs, catalog, and metrics. Give the password only to people trusted with customer messages and contacts, and rotate it when staff changes.

### Catalog source of truth

Assortment and prices live in the local SQLite `catalog_items` table and are edited in `/catalog`. Google Sheets is not used for stock availability anymore; order rows are still written to Sheets through `order_sheet.py`.

The `/stock` Telegram command still works as a fast mobile update path and writes into the same catalog, so the bot reads the change immediately. Items are never physically deleted from the admin UI: hiding sets `is_active = 0` and keeps history. Each catalog change records `catalog_updated` with item name, changed field, and editor only — no prices or quantities in the event payload.

Required `.env` values:

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=use-a-strong-password-here
```

Run locally:

```bash
uv run uvicorn amelia_manager.admin:app --host 127.0.0.1 --port 8000
```

### Safe external access

#### Quick access: Cloudflare Tunnel

```bash
cloudflared tunnel --url http://localhost:8000
```

Cloudflare gives an HTTPS URL and you do not need to open router/firewall ports.

#### Permanent access: VPS + Caddy

Run the admin app on localhost only:

```bash
uv run uvicorn amelia_manager.admin:app --host 127.0.0.1 --port 8000
```

Caddy reverse proxy example:

```caddy
admin.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy obtains and renews Let's Encrypt certificates automatically.

#### Do not do this

- Do not expose the admin UI over plain HTTP without TLS.
- Do not forward a home-router port directly to the admin UI.
- Do not bind the admin UI to `0.0.0.0` unless it is behind a trusted TLS reverse proxy.
- Do not run with default or empty admin credentials.

## Safety notes

Never commit runtime secrets or customer data. The repository intentionally ignores:

- `.env`
- `data/` and Telethon `*.session` files
- `logs/`
- `.venv/`
- Python/test caches

Use `AUTO_REPLY_ENABLED=false` for dry-runs. In dry-run mode the runtime should not send customer/admin messages or mark admin requests as sent.

## Privacy and retention

Runtime data is stored locally in the SQLite database configured by `DATABASE_URL` (default: `data/amelia_manager.sqlite3`). This can include Telegram IDs/usernames, message history, order cards, phone numbers, names, addresses, postcard text, and company stock notes. Keep `data/` out of git and restrict access on the deployment host.

`PII_RETENTION_DAYS` controls automatic cleanup at listener startup and in the daily `RETENTION_CLEANUP_INTERVAL_HOURS` background loop:

- messages older than the retention window are deleted;
- old completed/sent order cards are anonymized by clearing names, phones, delivery address, postcard text, and profile-specific `custom_fields`;
- recent active orders are kept intact so the manager can continue the current conversation.

Default message/order-card retention is 30 days. `EVENT_RETENTION_DAYS` defaults to 90 days because anonymized events intentionally outlive messages for metrics. For SQLite backups, use the online `.backup` command rather than copying the database file directly; see `docs/operations.md`. For manual deletion requests, use the repository erasure helper from a maintenance shell:

```bash
uv run python - <<'PY'
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository, path_from_sqlite_url

repo = SQLiteRepository(path_from_sqlite_url(Settings().database_url))
print(repo.delete_client_data_by_telegram_id(123456789))
PY
```

Replace `123456789` with the customer's Telegram ID. The helper removes that client's messages, orders, and client row.
