import pytest

from amelia_manager.config import Settings
from amelia_manager.telegram_runtime import send_typing_and_messages


class FakeAction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeTelegramClient:
    def __init__(self):
        self.sent = []

    def action(self, sender_id, action):
        return FakeAction()

    async def send_message(self, sender_id, message):
        self.sent.append(message)


def test_settings_default_conversation_memory_limits():
    settings = Settings(
        telegram_api_id=1,
        telegram_api_hash="hash",
        telegram_phone="+10000000000",
        admin_chat_id=123,
        llm_api_key="key",
    )

    assert settings.conversation_history_limit == 20
    assert settings.conversation_memory_days == 7
    assert settings.max_reply_chars == 400


@pytest.mark.asyncio
async def test_send_typing_and_messages_caps_each_reply_to_max_chars():
    client = FakeTelegramClient()
    long_message = "А" * 450

    await send_typing_and_messages(
        client,
        sender_id=123,
        messages=[long_message],
        initial_delay=0,
        between_delay=0,
        max_chars=400,
    )

    assert len(client.sent) == 1
    assert len(client.sent[0]) <= 400
    assert client.sent[0].endswith("…")
