import pytest

from amelia_manager.telegram_runtime import send_typing_and_messages


class FakeClient:
    def __init__(self):
        self.actions = []
        self.sent = []

    def action(self, sender_id, action):
        self.actions.append((sender_id, type(action).__name__))
        return self

    async def __aenter__(self):
        self.actions.append(("entered", None))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.actions.append(("exited", None))

    async def send_message(self, sender_id, message):
        self.sent.append((sender_id, message))


@pytest.mark.asyncio
async def test_send_typing_and_messages_uses_action_context_manager():
    client = FakeClient()

    await send_typing_and_messages(client, sender_id=123, messages=["Привет"], initial_delay=0, between_delay=0)

    assert (123, "SendMessageTypingAction") in client.actions
    assert ("entered", None) in client.actions
    assert client.sent == [(123, "Привет")]


@pytest.mark.asyncio
async def test_send_typing_and_messages_uses_random_delay_between_min_and_max():
    client = FakeClient()
    sleeps = []

    async def fake_sleep(value):
        sleeps.append(value)

    await send_typing_and_messages(
        client,
        sender_id=123,
        messages=["Привет"],
        initial_delay=12,
        max_initial_delay=90,
        between_delay=0,
        sleep=fake_sleep,
        random_between=lambda left, right: 42,
    )

    assert sleeps[0] == 42
