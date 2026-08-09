from amelia_manager.risk import RiskLevel, classify_risk


def test_regular_bouquet_request_is_low_risk():
    assert classify_risk("Здравствуйте, нужен букет девушке сегодня") == RiskLevel.LOW


def test_anonymous_delivery_is_low_risk():
    assert classify_risk("Можно анонимно доставить?") == RiskLevel.LOW


def test_refund_or_complaint_is_high_risk():
    assert classify_risk("Мне привезли не то, хочу возврат") == RiskLevel.HIGH
    assert classify_risk("Хочу пожаловаться на заказ") == RiskLevel.HIGH


def test_wedding_and_corporate_orders_need_human_attention():
    assert classify_risk("Нужен свадебный букет и оформление зала") == RiskLevel.HIGH
    assert classify_risk("Нужен корпоративный заказ на 40 букетов") == RiskLevel.HIGH


def test_out_of_city_and_late_delivery_are_medium_risk():
    assert classify_risk("Доставите за город в область?") == RiskLevel.MEDIUM
    assert classify_risk("Можно доставить после 22:00?") == RiskLevel.MEDIUM
