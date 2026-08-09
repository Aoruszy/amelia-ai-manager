import pytest

from amelia_manager.conversation_engine import ConversationEngine


class FailingLLM:
    async def generate(self, prompt: str) -> str:
        raise AssertionError("photo-only fallback should not require an LLM call")


@pytest.mark.asyncio
async def test_engine_replies_to_photo_only_message_without_vision():
    action = await ConversationEngine(FailingLLM()).handle_messages(
        client_summary="Новый клиент Telegram.",
        recent_messages=["Клиент: [photo]"],
        stage="new_lead",
    )

    assert action.kind == "send"
    text = "\n".join(action.messages).lower()
    assert "вижу фото" in text
    assert "бюджет" in text


@pytest.mark.asyncio
async def test_engine_replies_to_non_photo_media_without_silence():
    action = await ConversationEngine(FailingLLM()).handle_messages(
        client_summary="Новый клиент Telegram.",
        recent_messages=["Клиент: [media]"],
        stage="new_lead",
    )

    assert action.kind == "send"
    assert "вижу вложение" in "\n".join(action.messages).lower()
