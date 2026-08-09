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
