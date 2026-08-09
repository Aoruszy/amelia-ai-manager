from __future__ import annotations

from amelia_manager.risk import RiskLevel


def format_admin_notification(
    *,
    title: str,
    client_label: str,
    stage: str,
    risk_level: RiskLevel,
    summary: str,
    last_message: str,
) -> str:
    return (
        f"🌸 {title} / Amelia Flowers\n"
        f"Клиент: {client_label}\n"
        f"Стадия: {stage}\n"
        f"Риск: {risk_level.value}\n\n"
        f"Кратко: {summary}\n\n"
        f"Последнее сообщение клиента:\n"
        f"\"{last_message}\""
    )
