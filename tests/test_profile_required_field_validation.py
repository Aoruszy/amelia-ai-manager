from amelia_manager.company_profile import BusinessField, CompanyProfile
from amelia_manager.order_card import OrderCard, is_ready_for_profile_case


def test_profile_required_fields_can_validate_non_florist_custom_case():
    profile = CompanyProfile(
        company_name="Dental Plus",
        manager_name="Марина",
        business_type="clinic",
        city="Калининград",
        tone="спокойный",
        required_fields={
            "appointment": [
                BusinessField("service", "услуга"),
                BusinessField("date", "дата"),
                BusinessField("time", "время"),
                BusinessField("patient_name", "имя пациента"),
                BusinessField("customer_phone", "телефон"),
            ]
        },
    )
    card = OrderCard(
        delivery_date="12 августа",
        delivery_time="15:00",
        sender_phone="89990000001",
        custom_fields={"service": "чистка зубов", "patient_name": "Ирина"},
    )

    assert is_ready_for_profile_case(card, profile, "appointment") is True


def test_profile_required_fields_detect_missing_custom_field():
    profile = CompanyProfile(
        company_name="Dental Plus",
        manager_name="Марина",
        business_type="clinic",
        city="Калининград",
        tone="спокойный",
        required_fields={"appointment": [BusinessField("service", "услуга"), BusinessField("patient_name", "имя пациента")]},
    )
    card = OrderCard(custom_fields={"service": "чистка зубов"})

    assert is_ready_for_profile_case(card, profile, "appointment") is False
