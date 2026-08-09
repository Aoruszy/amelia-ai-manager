# Universal AI Manager / Amelia profile

AI Telegram manager core with a first company profile for Amelia Flowers.

## MVP defaults

- Telegram user account via Telethon.
- Manager persona: Алина.
- Company profile: `COMPANY_PROFILE_NAME=amelia_flowers`.
- Admin notifications to Даня in Telegram.
- Auto-reply can be enabled for everyone who writes to the account.
- First LLM target: free Gemini, later switch to GPT API.

## Setup

```bash
uv sync --extra dev
cp .env.example .env
# fill TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, ADMIN_CHAT_ID, LLM_API_KEY
uv run pytest
uv run python -m amelia_manager.main
```
