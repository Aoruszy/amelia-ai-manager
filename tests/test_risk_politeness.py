from amelia_manager.risk import RiskLevel, classify_risk


def test_polite_please_is_not_complaint_high_risk():
    text = "Напишите, пожалуйста, ваши имя и телефон. Гайдара 173, получатель Ольга"

    assert classify_risk(text) == RiskLevel.LOW


def test_real_complaint_is_still_high_risk():
    assert classify_risk("Я хочу пожаловаться на заказ") == RiskLevel.HIGH
    assert classify_risk("Пожалуюсь, если не вернете деньги") == RiskLevel.HIGH
