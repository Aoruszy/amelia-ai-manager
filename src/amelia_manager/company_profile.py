from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BusinessField:
    code: str
    label: str
    required: bool = True


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
        shop_hours="09:00–20:00",
        delivery_hours="08:00–22:00",
        free_delivery_from=5000,
        delivery_city_price=400,
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
    )
}


def load_company_profile(name: str = "amelia_flowers") -> CompanyProfile:
    try:
        return _DEFAULT_PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown company profile: {name}") from exc
