from amelia_manager.config import Settings
from amelia_manager.order_state import extract_order_state


def test_delivery_recipient_name_is_extracted_from_second_name_phone_pair_after_recipient_prompt():
    state = extract_order_state(
        [
            "Клиент: Даниил 89990000013",
            "Менеджер: Имя и номер телефона получателя подскажите, пожалуйста?",
            "Клиент: Ольга 89990000004",
        ]
    )

    assert state.sender_name == "Даниил"
    assert state.sender_phone == "89990000013"
    assert state.recipient_name == "Ольга"
    assert state.recipient_phone == "89990000004"


def test_default_memory_limit_is_wide_enough_for_full_delivery_order_flow():
    settings = Settings(
        telegram_api_id=1,
        telegram_api_hash="hash",
        telegram_phone="+10000000000",
        admin_chat_id=123,
        llm_api_key="key",
    )

    assert settings.conversation_history_limit == 20
