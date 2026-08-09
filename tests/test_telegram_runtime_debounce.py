import asyncio

import pytest

from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.order_card import OrderCard
from amelia_manager.telegram_runtime import PerSenderDebounceProcessor, build_admin_order_request_if_needed


@pytest.mark.asyncio
async def test_three_rapid_messages_from_same_sender_are_processed_as_one_turn():
    processed: list[tuple[int, list[str]]] = []

    async def process_turn(sender_id: int, messages: list[str]) -> None:
        processed.append((sender_id, messages))

    processor = PerSenderDebounceProcessor(buffer_seconds=0.01, process_turn=process_turn)

    await asyncio.gather(
        processor.enqueue(sender_id=123, text="Здравствуйте"),
        processor.enqueue(sender_id=123, text="Нужен букет"),
        processor.enqueue(sender_id=123, text="До 5000"),
    )
    await processor.wait_idle()

    assert processed == [(123, ["Здравствуйте", "Нужен букет", "До 5000"])]


@pytest.mark.asyncio
async def test_messages_from_same_sender_never_process_concurrently():
    started_first = asyncio.Event()
    release_first = asyncio.Event()
    active_turns = 0
    max_active_turns = 0
    processed: list[list[str]] = []

    async def process_turn(sender_id: int, messages: list[str]) -> None:
        nonlocal active_turns, max_active_turns
        active_turns += 1
        max_active_turns = max(max_active_turns, active_turns)
        processed.append(messages)
        if messages == ["первое"]:
            started_first.set()
            await release_first.wait()
        active_turns -= 1

    processor = PerSenderDebounceProcessor(buffer_seconds=0.01, process_turn=process_turn)

    await processor.enqueue(sender_id=123, text="первое")
    await started_first.wait()
    await processor.enqueue(sender_id=123, text="второе")
    release_first.set()
    await processor.wait_idle()

    assert processed == [["первое"], ["второе"]]
    assert max_active_turns == 1


@pytest.mark.asyncio
async def test_rapid_ready_order_messages_create_one_admin_request(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    client = repo.upsert_client(telegram_id=123, username="client")
    order = repo.get_or_create_active_order(client_id=client.id)
    repo.update_order_card(
        order_id=order.id,
        card=OrderCard(
            budget=5000,
            colors=["белый"],
            fulfillment_type="pickup",
            delivery_date="today",
            delivery_time="18:00",
            sender_name="Даниил",
            sender_phone="89990000006",
            payment_method="transfer",
        ),
    )
    admin_requests: list[str] = []

    async def process_turn(sender_id: int, messages: list[str]) -> None:
        db_client = repo.upsert_client(telegram_id=sender_id, username="client")
        for message in messages:
            repo.add_message(client_id=db_client.id, direction="in", text=message)
        active_order = repo.get_active_order(client_id=db_client.id)
        text = build_admin_order_request_if_needed(repo, order=active_order, client_label="@client / 123")
        if text:
            admin_requests.append(text)

    processor = PerSenderDebounceProcessor(buffer_seconds=0.01, process_turn=process_turn)

    await asyncio.gather(
        processor.enqueue(sender_id=123, text="готово"),
        processor.enqueue(sender_id=123, text="спасибо"),
        processor.enqueue(sender_id=123, text="жду"),
    )
    await processor.wait_idle()

    assert len(admin_requests) == 1
    assert repo.get_active_order(client_id=client.id).card.admin_request_sent is True


@pytest.mark.asyncio
async def test_process_turn_exception_does_not_drop_followup_messages_or_kill_sender_loop():
    attempts: list[list[str]] = []

    async def process_turn(sender_id: int, messages: list[str]) -> None:
        attempts.append(messages)
        if messages == ["сломайся"]:
            raise RuntimeError("temporary failure")

    processor = PerSenderDebounceProcessor(buffer_seconds=0.01, process_turn=process_turn)

    await processor.enqueue(sender_id=123, text="сломайся")
    await processor.wait_idle()
    await processor.enqueue(sender_id=123, text="следующее")
    await processor.wait_idle()

    assert attempts == [["сломайся"], ["следующее"]]
