from amelia_manager.telegram_runtime import IncomingMessage, event_text_with_media_placeholder, should_process_incoming
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


class FakeTelegramEvent:
    def __init__(self, *, raw_text: str = "", photo=None, media=None):
        self.raw_text = raw_text
        self.photo = photo
        self.media = media


def test_photo_only_event_gets_photo_placeholder_so_it_is_not_ignored():
    text = event_text_with_media_placeholder(FakeTelegramEvent(photo=object(), media=object()))
    msg = IncomingMessage(sender_id=1, text=text, is_private=True, outgoing=False)

    assert text == "[photo]"
    assert should_process_incoming(msg, Settings()) is True


def test_photo_caption_keeps_caption_and_photo_placeholder():
    text = event_text_with_media_placeholder(FakeTelegramEvent(raw_text="Вот такой букет", photo=object(), media=object()))

    assert text == "Вот такой букет\n[photo]"


def test_non_photo_media_event_gets_media_placeholder():
    text = event_text_with_media_placeholder(FakeTelegramEvent(media=object()))

    assert text == "[media]"
