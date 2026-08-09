from amelia_manager.risk import RiskCategory, RiskLevel, assess_risk, classify_risk


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


def test_benign_substrings_do_not_escalate():
    assert assess_risk("Ужасно красивый букет, хочу такой же").category == RiskCategory.NONE
    assert assess_risk("Какая у вас область доставки по городу?").category == RiskCategory.NONE
    assert assess_risk("А скидки бывают?").level == RiskLevel.MEDIUM
    assert assess_risk("А скидки бывают?").category == RiskCategory.DISCOUNT


def test_risk_assessment_categories_are_specific():
    assert assess_risk("Мне привезли не то, хочу возврат").category == RiskCategory.COMPLAINT_REFUND
    assert assess_risk("Нужен корпоративный заказ на 40 букетов").category == RiskCategory.CUSTOM_ORDER
    assert assess_risk("Есть редкие пионы в наличии прямо сейчас?").category == RiskCategory.STOCK_UNCERTAINTY
    assert assess_risk("Доставка ночью за город возможна?").category == RiskCategory.OUT_OF_AREA_DELIVERY
