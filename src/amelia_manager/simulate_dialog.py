from __future__ import annotations

import argparse
import asyncio

from amelia_manager.config import Settings
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.llm_client import GeminiClient


def format_simulation_result(*, kind: str, messages: list[str]) -> str:
    lines = [f"Action: {kind}", "Messages:"]
    lines.extend(f"{index}. {message}" for index, message in enumerate(messages, start=1))
    return "\n".join(lines)


async def simulate(message: str) -> str:
    settings = Settings()
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY is required for simulation")
    llm = GeminiClient(api_key=settings.llm_api_key, model=settings.llm_model)
    engine = ConversationEngine(llm)
    action = await engine.handle_messages(
        client_summary="Новый клиент, данных пока нет.",
        recent_messages=[f"Клиент: {message}"],
        stage="new_lead",
    )
    return format_simulation_result(kind=action.kind, messages=action.messages)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("message")
    args = parser.parse_args()
    print(asyncio.run(simulate(args.message)))


if __name__ == "__main__":
    main()
