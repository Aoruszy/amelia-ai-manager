# Universal AI Manager / Amelia profile

AI Telegram manager core with a first company profile for Amelia Flowers.

## MVP defaults

- Telegram user account via Telethon.
- Manager persona: Алина.
- Company profile: `COMPANY_PROFILE_NAME=amelia_flowers`.
- Admin notifications in Telegram via `ADMIN_CHAT_ID`.
- Auto-reply can be enabled for everyone who writes to the account.
- Current LLM target: Gemini; OpenAI/GPT can be added as a provider later.

## Setup

```bash
uv sync --extra dev
cp .env.example .env
# fill TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, ADMIN_CHAT_ID, LLM_API_KEY
uv run pytest -q
uv run python -m amelia_manager.telegram_runtime
```

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

`PII_RETENTION_DAYS` controls automatic cleanup at listener startup:

- messages older than the retention window are deleted;
- old completed/sent order cards are anonymized by clearing names, phones, delivery address, postcard text, and profile-specific `custom_fields`;
- recent active orders are kept intact so the manager can continue the current conversation.

Default retention is 30 days. For manual deletion requests, use the repository erasure helper from a maintenance shell:

```bash
uv run python - <<'PY'
from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository, path_from_sqlite_url

repo = SQLiteRepository(path_from_sqlite_url(Settings().database_url))
print(repo.delete_client_data_by_telegram_id(123456789))
PY
```

Replace `123456789` with the customer's Telegram ID. The helper removes that client's messages, orders, and client row.
