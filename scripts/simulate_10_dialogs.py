from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from amelia_manager.config import Settings
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.db.repository import SQLiteRepository
from amelia_manager.llm_client import build_llm_client
from amelia_manager.stock import build_stock_context, parse_stock_text
from amelia_manager.telegram_runtime import build_admin_order_request_if_needed, update_active_order_from_messages

SCENARIOS = [
    ["Здравствуйте", "Нужны цветы", "Бюджет 5000, выбираю девушке", "Розовый желтый белый", "А какие цветы там будут?", "Самовывоз", "Оплачу на месте", "Даниил 89990000001", "18:00"],
    ["Добрый день", "Хочу букет маме до 3000", "Нежный, можно бело-розовый", "Доставка", "Сегодня к 19:00", "Ленинский 25", "Я Антон 89990000002, получатель Марина 89990000003", "Оплачу переводом"],
    ["Привет", "Нужен букет без хризантем", "До 7000, девушке", "Сине белый с гортензией", "Самовывоз завтра", "К 12:30", "Олег 89990000004", "Картой"],
    ["Здравствуйте, можно анонимную доставку?", "Букет до 6000", "Красные розы", "Доставка сегодня 20:00", "Гайдара 173", "Отправитель Даня 89990000005, получатель Оля 89990000006", "Оплата СБП"],
    ["Хочу цветы", "До 2500", "Что-нибудь яркое", "Самовывоз", "Сегодня 17:00", "Ирина 89990000007", "Наличные"],
    ["Добрый вечер", "Нужен букет жене", "Бюджет 10000", "Премиальный белый с зеленью", "Доставка завтра 11:00", "ул. Озерная 7", "Я Сергей 89990000008, получатель Алена 89990000009", "перевод"],
    ["Здравствуйте", "Есть пионы?", "Если нет, подберите похожий нежный", "До 5000", "Самовывоз сегодня 16:00", "Мария 89990000010", "Оплачу на месте"],
    ["Нужны цветы", "Для мамы, бюджет 4000", "Белые и розовые", "Можно открытку: любимой маме", "Доставка", "Завтра 14:00", "Сергеева 10", "Я Павел 89990000011, получатель Наталья 89990000012", "картой"],
    ["Хочу букет", "Бюджет 5000", "Не знаю какой", "Девушке", "Пусть будет нежный", "Самовывоз", "Сегодня 18:30", "Максим 89990000013", "оплата при получении"],
    ["Добрый день, нужна корзина цветов", "До 8000", "Яркая, без хризантем", "Доставка сегодня вечером", "К 21:00 можно?", "Мира 5", "Отправитель Кира 89990000014, получатель Вера 89990000015", "СБП"],
]

STOCK = """/stock
гортензия голубая — 8
розы белые — мало
розы красные — много
эустома белая — есть
эустома розовая — есть
пионы — нет
хризантемы кустовые — много
гипсофила белая — много
корзины средние — мало
"""


def bad_flags(text: str) -> list[str]:
    low = text.lower().replace("ё", "е")
    flags = []
    if low.count("🙂") >= 2:
        flags.append("too_many_same_smile")
    if "я ai" in low or "я бот" in low:
        flags.append("identity_leak")
    if "получател" in low and "самовывоз" in low:
        flags.append("pickup_recipient_question")
    if "доставка или самовывоз" in low and ("оттен" not in low and "цвет" not in low and "стиль" not in low):
        flags.append("early_fulfillment_question")
    if "уточню у флориста" in low or "пришлю фото" in low:
        flags.append("unsupported_promise")
    return flags


async def main() -> None:
    settings = Settings()
    llm = build_llm_client(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
    )
    engine = ConversationEngine(llm)
    outputs = []
    all_flags = Counter()

    with TemporaryDirectory() as tmp:
        for idx, scenario in enumerate(SCENARIOS, start=1):
            repo = SQLiteRepository(Path(tmp) / f"dialog_{idx}.sqlite3")
            repo.initialize()
            repo.replace_daily_stock(stock_date=date.today(), items=parse_stock_text(STOCK), updated_by=1)
            client = repo.upsert_client(telegram_id=1000 + idx, username=f"client{idx}")
            history: list[str] = []
            dialog_flags = []
            outputs.append(f"\n## Диалог {idx}")
            for user_text in scenario:
                history.append(f"Клиент: {user_text}")
                card = update_active_order_from_messages(repo, client_id=client.id, recent_messages=history)
                stock_context = build_stock_context(
                    items=repo.list_daily_stock(stock_date=date.today()),
                    colors=card.colors,
                    desired_text="\n".join(history),
                    stock_date=date.today(),
                )
                action = await engine.handle_messages(
                    client_summary=f"Тестовый клиент {idx}",
                    recent_messages=history,
                    stage="new_lead",
                    order_card=card,
                    stock_context=stock_context,
                )
                reply = " | ".join(action.messages)
                flags = bad_flags(reply)
                dialog_flags.extend(flags)
                outputs.append(f"Клиент: {user_text}")
                outputs.append(f"Алина: {reply}")
                if flags:
                    outputs.append(f"FLAGS: {', '.join(flags)}")
                for msg in action.messages:
                    history.append(f"Менеджер: {msg}")
                    repo.add_message(client_id=client.id, direction="out", text=msg)
                repo.add_message(client_id=client.id, direction="in", text=user_text)
            order = repo.get_active_order(client_id=client.id)
            admin = build_admin_order_request_if_needed(repo, order=order, client_label=f"@client{idx} / {1000+idx}") if order else None
            outputs.append("ADMIN_REQUEST: " + ("YES" if admin else "NO"))
            if admin:
                outputs.append(admin.replace("\n", " | "))
            if dialog_flags:
                all_flags.update(dialog_flags)

    print("\n".join(outputs))
    print("\n## SUMMARY")
    print("flags:", dict(all_flags))


if __name__ == "__main__":
    asyncio.run(main())
