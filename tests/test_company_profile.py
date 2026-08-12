from amelia_manager.company_profile import BusinessField, CompanyProfile, load_company_profile


def test_loads_default_amelia_company_profile():
    profile = load_company_profile("amelia_flowers")

    assert profile.company_name == "Amelia Flowers"
    assert profile.manager_name == "Алина"
    assert profile.business_type == "florist"
    assert profile.city == "Калининград"
    assert profile.pickup_address == "Сергеева, 61"
    assert "букеты" in profile.services
    assert "при самовывозе нужны контакты клиента; контакты получателя нужны только для доставки" in profile.business_rules


def test_company_profile_defines_required_fields_per_case_type():
    profile = load_company_profile("amelia_flowers")

    pickup_codes = [field.code for field in profile.required_fields["pickup"]]
    delivery_codes = [field.code for field in profile.required_fields["delivery"]]

    assert pickup_codes == [
        "product_preferences",
        "budget",
        "date",
        "time",
        "customer_name",
        "customer_phone",
    ]
    assert "delivery_address" not in pickup_codes
    assert "recipient_name" not in pickup_codes
    assert "delivery_address" in delivery_codes
    assert "recipient_phone" in delivery_codes


def test_company_profile_can_be_constructed_for_other_businesses():
    profile = CompanyProfile(
        company_name="Dental Plus",
        manager_name="Марина",
        business_type="clinic",
        city="Калининград",
        tone="спокойный, заботливый",
        services=["чистка зубов", "лечение"],
        required_fields={
            "appointment": [
                BusinessField(code="service", label="услуга"),
                BusinessField(code="date", label="дата"),
                BusinessField(code="customer_phone", label="телефон"),
            ]
        },
        business_rules=["не ставить диагноз по переписке"],
    )

    assert profile.business_type == "clinic"
    assert profile.required_fields["appointment"][0].code == "service"
