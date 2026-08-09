from __future__ import annotations

from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.risk import RiskLevel


def format_admin_notification(
    *,
    title: str,
    client_label: str,
    stage: str,
    risk_level: RiskLevel,
    summary: str,
    last_message: str,
    company_profile: CompanyProfile | None = None,
) -> str:
    profile = company_profile or load_company_profile("amelia_flowers")
    return (
        f"🌸 {title} / {profile.company_name}\n"
        f"Клиент: {client_label}\n"
        f"Стадия: {stage}\n"
        f"Риск: {risk_level.value}\n\n"
        f"Кратко: {summary}\n\n"
        f"Последнее сообщение клиента:\n"
        f"\"{last_message}\""
    )
