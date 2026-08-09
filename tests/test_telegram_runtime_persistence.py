from amelia_manager.telegram_runtime import IncomingMessage, persist_incoming_message
from amelia_manager.db.repository import SQLiteRepository


def test_persist_incoming_message_creates_client_and_message(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.sqlite3")
    repo.initialize()
    incoming = IncomingMessage(sender_id=123, text="Нужен букет", is_private=True, outgoing=False)

    client = persist_incoming_message(repo, incoming, username="client_user")

    assert client.telegram_id == 123
    assert client.username == "client_user"
    messages = repo.list_messages(client_id=client.id)
    assert len(messages) == 1
    assert messages[0].direction == "in"
    assert messages[0].text == "Нужен букет"
