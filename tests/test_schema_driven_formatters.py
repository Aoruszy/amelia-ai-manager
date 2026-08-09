from amelia_manager.client_order_summary import format_client_order_summary
from amelia_manager.company_profile import CompanyProfile
from amelia_manager.order_card import OrderCard
from amelia_manager.order_request import format_admin_order_request


def clinic_profile() -> CompanyProfile:
    return CompanyProfile(
        company_name="Dental Plus",
        manager_name="Марина",
        business_type="clinic",
        city="Калининград",
        tone="спокойный",
        services=["чистка зубов"],
    )


def clinic_card() -> OrderCard:
    return OrderCard(
        delivery_date="12 августа",
        delivery_time="15:00",
        sender_name="Ирина",
        sender_phone="89990000001",
        custom_fields={"service": "чистка зубов", "patient_name": "Ирина"},
    )


def test_admin_request_can_format_non_florist_custom_fields_without_florist_labels():
    text = format_admin_order_request(
        order_id=1,
        client_label="@client",
        card=clinic_card(),
        company_profile=clinic_profile(),
        case_type="appointment",
    )

    assert "Новая заявка Dental Plus" in text
    assert "service: чистка зубов" in text
    assert "patient_name: Ирина" in text
    assert "Пожелания" not in text
    assert "Самовывоз: Сергеева" not in text


def test_client_summary_can_format_non_florist_custom_fields_without_bouquet_label():
    text = format_client_order_summary(clinic_card(), company_profile=clinic_profile())

    assert "Итог заявки" in text
    assert "service: чистка зубов" in text
    assert "patient_name: Ирина" in text
    assert "Букет" not in text
