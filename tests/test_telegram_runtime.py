from amelia_manager.telegram_runtime import IncomingMessage, should_process_incoming
from amelia_manager.config import Settings


def test_should_ignore_outgoing_messages():
    msg = IncomingMessage(sender_id=1, text="hi", is_private=True, outgoing=True)

    assert should_process_incoming(msg, Settings()) is False


def test_should_ignore_group_messages():
    msg = IncomingMessage(sender_id=1, text="hi", is_private=False, outgoing=False)

    assert should_process_incoming(msg, Settings()) is False


def test_should_process_everyone_when_allowlist_disabled():
    settings = Settings(allow_only_test_users=False)
    msg = IncomingMessage(sender_id=999, text="hi", is_private=True, outgoing=False)

    assert should_process_incoming(msg, settings) is True


def test_should_respect_allowlist_when_enabled():
    settings = Settings(allow_only_test_users=True, test_allowlist_ids="123")

    allowed = IncomingMessage(sender_id=123, text="hi", is_private=True, outgoing=False)
    blocked = IncomingMessage(sender_id=456, text="hi", is_private=True, outgoing=False)

    assert should_process_incoming(allowed, settings) is True
    assert should_process_incoming(blocked, settings) is False
