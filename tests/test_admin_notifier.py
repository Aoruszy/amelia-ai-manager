from amelia_manager.admin_notifier import format_admin_notification
from amelia_manager.risk import RiskLevel


def test_format_admin_notification_contains_client_stage_risk_and_message():
    text = format_admin_notification(
        title="Новый лид",
        client_label="@client / 123",
        stage="new_lead",
        risk_level=RiskLevel.LOW,
        summary="Хочет букет девушке сегодня",
        last_message="Здравствуйте, нужен букет",
    )

    assert "Новый лид" in text
    assert "@client / 123" in text
    assert "new_lead" in text
    assert "low" in text
    assert "Хочет букет девушке сегодня" in text
    assert "Здравствуйте, нужен букет" in text
