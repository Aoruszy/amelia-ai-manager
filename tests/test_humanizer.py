from amelia_manager.humanizer import split_into_telegram_messages


def test_short_reply_stays_single_message():
    assert split_into_telegram_messages("Да, конечно. На сегодня нужен?") == ["Да, конечно. На сегодня нужен?"]


def test_long_paragraphs_split_into_short_messages():
    text = "Поняла вас.\n\nЕсли в пределах 3000–4000 ₽, можно посмотреть сборный букет.\n\nДоставка нужна сегодня?"

    assert split_into_telegram_messages(text) == [
        "Поняла вас.",
        "Если в пределах 3000–4000 ₽, можно посмотреть сборный букет.",
        "Доставка нужна сегодня?",
    ]
