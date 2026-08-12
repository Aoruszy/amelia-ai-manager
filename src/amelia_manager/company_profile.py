from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BusinessField:
    code: str
    label: str
    required: bool = True


_DEFAULT_CATEGORIES = (
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


@dataclass(frozen=True)
class CompanyProfile:
    company_name: str
    manager_name: str
    business_type: str
    city: str
    tone: str
    services: list[str] = field(default_factory=list)
    required_fields: dict[str, list[BusinessField]] = field(default_factory=dict)
    business_rules: list[str] = field(default_factory=list)
    pickup_address: str | None = None
    public_phone: str | None = None
    shop_hours: str | None = None
    delivery_hours: str | None = None
    free_delivery_from: int | None = None
    delivery_city_price: int | None = None
    nearest_delivery_time: str | None = None
    telegram_primary: str | None = None
    telegram_secondary: str | None = None
    product_categories: tuple[str, ...] = field(default_factory=tuple)
    faq: dict[str, str] = field(default_factory=dict)
    timezone_name: str = "Europe/Kaliningrad"
    stock_terms: tuple[str, ...] = ("в наличии",)
    alternative_offer_text: str = "могу предложить близкий вариант"
    sensitive_occasion_tone_rule: str = "сдержанно, без эмодзи, по делу и коротко"
    sensitive_occasion_forbidden_words: tuple[str, ...] = ()

    def required_field_codes(self, case_type: str) -> list[str]:
        return [field.code for field in self.required_fields.get(case_type, []) if field.required]


_DEFAULT_PROFILES = {
    "amelia_flowers": CompanyProfile(
        company_name="Amelia Flowers",
        manager_name="Алина",
        business_type="florist",
        city="Калининград",
        tone="живой, вежливый, короткий, заботливый",
        pickup_address="Сергеева, 61",
        public_phone="+7 (995) 338-31-67",
        telegram_primary="@order_amelia",
        telegram_secondary="@ameliaflowers39",
        shop_hours="09:00–20:00",
        delivery_hours="08:00–22:00",
        nearest_delivery_time="от 1 часа после оформления",
        free_delivery_from=5000,
        delivery_city_price=400,
        stock_terms=("пионы", "редкие", "в наличии", "точно есть"),
        alternative_offer_text="могу предложить близкий вариант по стилю",
        sensitive_occasion_tone_rule="сдержанно, без эмодзи, без радостного тона; по делу и коротко",
        sensitive_occasion_forbidden_words=("яркий", "нежный", "порадовать", "сюрприз"),
        product_categories=_DEFAULT_CATEGORIES,
        services=[
            "букеты",
            "цветочные корзины",
            "композиции",
            "доставка цветов",
            "самовывоз",
        ],
        required_fields={
            "pickup": [
                BusinessField("product_preferences", "пожелания к букету"),
                BusinessField("budget", "бюджет"),
                BusinessField("date", "дата"),
                BusinessField("time", "время"),
                BusinessField("customer_name", "имя клиента"),
                BusinessField("customer_phone", "телефон клиента"),
            ],
            "delivery": [
                BusinessField("product_preferences", "пожелания к букету"),
                BusinessField("budget", "бюджет"),
                BusinessField("date", "дата"),
                BusinessField("time", "время"),
                BusinessField("delivery_address", "адрес доставки"),
                BusinessField("recipient_name", "имя получателя"),
                BusinessField("recipient_phone", "телефон получателя"),
                BusinessField("customer_name", "имя отправителя"),
                BusinessField("customer_phone", "телефон отправителя"),
                BusinessField("payment_method", "способ оплаты"),
            ],
        },
        business_rules=[
            "не спрашивать доставку/самовывоз до понимания букета, стиля или гаммы",
            "не спрашивать имя/телефон получателя при самовывозе",
            "адрес Сергеева, 61 использовать только как адрес самовывоза",
            "адрес Сергеева 61 использовать только как адрес самовывоза",
            "не обещать конкретное наличие цветов без актуального stock",
            "заявку админу отправлять один раз после готовности обязательных полей",
        ],
        faq={
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
        },
    )
}


def load_company_profile(name: str = "amelia_flowers") -> CompanyProfile:
    try:
        return _DEFAULT_PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown company profile: {name}") from exc
