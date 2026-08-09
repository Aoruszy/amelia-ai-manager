from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoreFacts:
    name: str
    manager_name: str
    city: str
    address: str
    phone: str
    telegram_primary: str
    telegram_secondary: str
    shop_hours: str
    delivery_hours: str
    nearest_delivery_time: str
    delivery_city_price: int
    free_delivery_from: int
    categories: tuple[str, ...]


_CATEGORIES = (
    "Пионы",
    "Розы",
    "Гипсофила",
    "Гортензия",
    "Сборные букеты",
    "Букеты до 3000 ₽",
    "Кустовые розы",
    "Для мамы",
    "Летние букеты",
    "Премиум",
    "Сумка с цветами",
    "Хризантема",
    "Ромашки",
    "Герберы",
    "Эустома",
    "Коробки и корзинки",
    "Пломбирки",
    "Плюшевые мишки",
    "Букет невесты",
    "Тюльпаны",
)

_FACTS = StoreFacts(
    name="Amelia Flowers",
    manager_name="Алина",
    city="Калининград",
    address="ул. Сергеева 61",
    phone="+7 (952) 050-95-55",
    telegram_primary="@order_amelia",
    telegram_secondary="@ameliaflowers39",
    shop_hours="09:00–20:00",
    delivery_hours="08:00–22:00",
    nearest_delivery_time="от 1 часа после оформления",
    delivery_city_price=400,
    free_delivery_from=5000,
    categories=_CATEGORIES,
)

_FAQ = {
    "delivery": (
        "По Калининграду доставка при заказе от 5000 ₽ бесплатная. "
        "Если заказ до 5000 ₽, доставка по городу — 400 ₽. "
        "Ближайшая доставка обычно от 1 часа после оформления, но точное время зависит "
        "от букета, адреса и загрузки. За город и после 22:00 лучше уточнить отдельно."
    ),
    "payment": (
        "Оплатить можно картой, через СБП/интернет-банк, электронными деньгами, "
        "наличными курьеру или в магазине. Для юрлиц доступен безналичный расчёт."
    ),
    "anonymous": (
        "Да, анонимная доставка возможна. Получатель узнает отправителя только если "
        "вы сами укажете имя или подпись в открытке."
    ),
    "photo_report": (
        "Фотоотчёт можно попросить заранее, я отмечу это в заказе. По умолчанию букеты "
        "не фотографируются, и выполнение зависит от текущей загрузки магазина."
    ),
    "unknown_address": (
        "Если адрес получателя неизвестен, можно указать телефон получателя. Курьер "
        "согласует с ним адрес и удобное время доставки."
    ),
    "same_as_photo": (
        "Цветы живые, поэтому букет может немного отличаться от фото по оттенкам и форме. "
        "Флорист сохраняет стиль, цветовую гамму и бюджет композиции."
    ),
}


def get_store_facts() -> StoreFacts:
    return _FACTS


def get_faq_answer(topic: str) -> str | None:
    return _FAQ.get(topic)
