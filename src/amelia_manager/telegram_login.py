from __future__ import annotations

import asyncio
from pathlib import Path

from telethon import TelegramClient

from amelia_manager.config import Settings


_REQUIRED_LOGIN_SETTINGS = (
    ("telegram_api_id", "TELEGRAM_API_ID"),
    ("telegram_api_hash", "TELEGRAM_API_HASH"),
    ("telegram_phone", "TELEGRAM_PHONE"),
)


def get_session_path(settings: Settings) -> Path:
    return Path("data/sessions") / settings.telegram_session_name


def validate_login_settings(settings: Settings) -> list[str]:
    missing: list[str] = []
    for attr_name, env_name in _REQUIRED_LOGIN_SETTINGS:
        if not getattr(settings, attr_name):
            missing.append(env_name)
    return missing


async def login(settings: Settings) -> None:
    missing = validate_login_settings(settings)
    if missing:
        raise RuntimeError(f"Missing required settings: {', '.join(missing)}")

    session_path = get_session_path(settings)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(
        str(session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    await client.start(phone=settings.telegram_phone)

    me = await client.get_me()
    print(f"Logged in as: id={me.id} username={me.username!r} phone={me.phone!r}")
    print(f"Session saved to: {session_path}.session")
    await client.disconnect()


def main() -> None:
    asyncio.run(login(Settings()))


if __name__ == "__main__":
    main()
