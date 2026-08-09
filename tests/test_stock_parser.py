from amelia_manager.stock import StockStatus, parse_stock_text


def test_parse_stock_text_understands_available_low_and_unavailable_items():
    items = parse_stock_text(
        """
        Наличие на сегодня:
        розы красные 60 см — много
        розы белые 50 см — мало
        гортензия голубая — 8 шт
        гортензия белая — нет
        эустома белая — есть
        пионы — нет
        """
    )

    assert [(item.name, item.status, item.quantity_number) for item in items] == [
        ("розы красные 60 см", StockStatus.AVAILABLE, None),
        ("розы белые 50 см", StockStatus.LOW, None),
        ("гортензия голубая", StockStatus.AVAILABLE, 8),
        ("гортензия белая", StockStatus.UNAVAILABLE, 0),
        ("эустома белая", StockStatus.AVAILABLE, None),
        ("пионы", StockStatus.UNAVAILABLE, 0),
    ]


def test_parse_stock_text_ignores_command_and_blank_lines():
    items = parse_stock_text("/stock\n\nрозы красные - 10\n")

    assert len(items) == 1
    assert items[0].name == "розы красные"
    assert items[0].quantity_number == 10
