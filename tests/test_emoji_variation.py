from amelia_manager.emoji_variation import vary_reply_emoji


def test_vary_reply_emoji_replaces_repeated_neutral_smile():
    outputs = {vary_reply_emoji("Здравствуйте 🙂 Чем могу помочь?", seed) for seed in range(6)}

    assert len(outputs) > 1
    assert all(text.count("🙂") <= 1 for text in outputs)


def test_vary_reply_emoji_limits_multiple_same_smiles_in_one_reply():
    text = vary_reply_emoji("Отлично 🙂 Записала 🙂 Жду вас 🙂", seed=2)

    assert text.count("🙂") <= 1
