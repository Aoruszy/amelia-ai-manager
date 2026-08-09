from __future__ import annotations

from dataclasses import dataclass

from amelia_manager.company_profile import CompanyProfile, load_company_profile


@dataclass(frozen=True)
class StoreFacts:
    name: str
    manager_name: str
    city: str
    address: str | None
    phone: str | None
    telegram_primary: str | None
    telegram_secondary: str | None
    shop_hours: str | None
    delivery_hours: str | None
    nearest_delivery_time: str | None
    delivery_city_price: int | None
    free_delivery_from: int | None
    categories: tuple[str, ...]


def get_store_facts(company_profile: CompanyProfile | None = None) -> StoreFacts:
    profile = company_profile or load_company_profile("amelia_flowers")
    return StoreFacts(
        name=profile.company_name,
        manager_name=profile.manager_name,
        city=profile.city,
        address=profile.pickup_address,
        phone=profile.public_phone,
        telegram_primary=profile.telegram_primary,
        telegram_secondary=profile.telegram_secondary,
        shop_hours=profile.shop_hours,
        delivery_hours=profile.delivery_hours,
        nearest_delivery_time=profile.nearest_delivery_time,
        delivery_city_price=profile.delivery_city_price,
        free_delivery_from=profile.free_delivery_from,
        categories=profile.product_categories,
    )


def get_faq_answer(topic: str, company_profile: CompanyProfile | None = None) -> str | None:
    profile = company_profile or load_company_profile("amelia_flowers")
    if topic == "delivery":
        return _delivery_faq(profile)
    return profile.faq.get(topic)


def _delivery_faq(profile: CompanyProfile) -> str | None:
    if profile.free_delivery_from is None or profile.delivery_city_price is None:
        return profile.faq.get("delivery")
    nearest = profile.nearest_delivery_time or "после оформления"
    hours = profile.delivery_hours or "по графику компании"
    return (
        f"По {profile.city} доставка при заказе от {profile.free_delivery_from} ₽ бесплатная. "
        f"Если заказ до {profile.free_delivery_from} ₽, доставка по городу — {profile.delivery_city_price} ₽. "
        f"Ближайшая доставка обычно {nearest}, но точное время зависит от заказа, адреса и загрузки. "
        f"Нестандартные адреса и доставку вне графика {hours} лучше уточнить отдельно."
    )
