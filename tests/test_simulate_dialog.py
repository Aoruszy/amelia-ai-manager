from amelia_manager.simulate_dialog import format_simulation_result


def test_format_simulation_result_includes_action_and_messages():
    text = format_simulation_result(kind="send", messages=["Привет", "На сегодня?"])

    assert "Action: send" in text
    assert "1. Привет" in text
    assert "2. На сегодня?" in text
