from amelia_manager.config import Settings
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.telegram_runtime import should_use_llm_extractor, update_active_order_from_messages, update_active_order_from_messages_with_optional_llm


class ExplodingLLM:
    async def generate(self, prompt: str) -> str:
        raise AssertionError("LLM extractor should be disabled by default")


def test_llm_extractor_disabled_by_default():
    assert should_use_llm_extractor(Settings()) is False


def test_optional_llm_extractor_uses_regex_when_disabled(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username=None)

    import asyncio
    card = asyncio.run(update_active_order_from_messages_with_optional_llm(
        repo,
        settings=Settings(),
        llm=ExplodingLLM(),
        client_id=client.id,
        recent_messages=["Клиент: Бюджет 5000, девушке"],
    ))

    assert card.budget == 5000
