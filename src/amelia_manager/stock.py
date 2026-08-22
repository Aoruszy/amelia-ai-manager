from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from amelia_manager.date_formatting import _today_in_timezone


class StockStatus(StrEnum):
    AVAILABLE = "available"
    LOW = "low"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class StockItem:
    name: str
    status: StockStatus
    quantity_text: str
    quantity_number: int | None = None
    price: int | None = None
    unit: str | None = None
    image_path: str | None = None


@dataclass(frozen=True)
class BudgetOption:
    name: str
    price: int
    unit: str | None = None
    image_path: str | None = None


@dataclass(frozen=True)
class BudgetOptions:
    items: list[BudgetOption]
    hide_names: bool = False


_BUDGET_UNKNOWN_RE = re.compile(
    r"\b(?:не\s+знаю|не\s+понимаю|затрудняюсь|сколько\s+нужно|какой\s+бюджет|на\s+ваше\s+усмотрение)\b"
)


def is_budget_unknown_answer(text: str) -> bool:
    return bool(_BUDGET_UNKNOWN_RE.search(text.lower().replace("ё", "е")))


def parse_stock_text(text: str) -> list[StockItem]:
    items: list[StockItem] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("/stock") or lowered.startswith("наличие на"):
            continue
        if "—" in line:
            name, qty = line.split("—", 1)
        elif "-" in line:
            name, qty = line.split("-", 1)
        else:
            continue
        name = name.strip().lower()
        quantity_text = qty.strip().lower()
        if not name or not quantity_text:
            continue
        quantity_number = _extract_quantity_number(quantity_text)
        items.append(
            StockItem(
                name=name,
                status=_status_from_quantity(quantity_text, quantity_number),
                quantity_text=quantity_text,
                quantity_number=0 if _status_from_quantity(quantity_text, quantity_number) == StockStatus.UNAVAILABLE else quantity_number,
            )
        )
    return items


def format_stock_ack(items: list[StockItem], *, source_type: str = "manual") -> str:
    if not items:
        return "Не нашла позиций в сообщении. Пришлите в формате: гортензия голубая — 8"
    lines = ["Приняла наличие на сегодня:"]
    for item in items:
        icon = {
            StockStatus.AVAILABLE: "✅",
            StockStatus.LOW: "⚠️",
            StockStatus.UNAVAILABLE: "❌",
        }[item.status]
        lines.append(f"{icon} {item.name} — {item.quantity_text}")
    if source_type == "sheets":
        lines.append("Ручной ввод перекроет таблицу до следующего успешного чтения Google Sheets.")
    return "\n".join(lines)


def build_stock_context(
    *,
    items: list[StockItem],
    colors: list[str],
    desired_text: str,
    stock_date: date | None,
    timezone_name: str = "Europe/Kaliningrad",
    today: date | None = None,
    composition_units: tuple[str, ...] = ("букет", "композиция", "корзина"),
    sensitive_occasion: bool = False,
    sensitive_forbidden_words: tuple[str, ...] = (),
    latest_client_text: str | None = None,
    include_budget_options: bool = False,
) -> str:
    today = today or _today_in_timezone(timezone_name)
    if not stock_date or not items:
        return "наличие на сегодня не внесено. Не обещай конкретные цветы; при необходимости скажи, что наличие нужно уточнить по смене."
    if stock_date != today:
        return "Наличие цветов устарело. Не обещай конкретные цветы; попроси уточнить актуальное наличие по смене."

    budget_options = BudgetOptions([])
    if include_budget_options:
        budget_options = select_budget_options(
            items,
            desired_text=latest_client_text if latest_client_text is not None else desired_text,
            composition_units=composition_units,
            sensitive_occasion=sensitive_occasion,
            sensitive_forbidden_words=sensitive_forbidden_words,
        )
    if include_budget_options and budget_options.items:
        lines = ["Варианты композиций из каталога для выбора бюджета:"]
        for option in budget_options.items:
            name = "вариант" if budget_options.hide_names else option.name
            lines.append(f"- {name} — {option.price} ₽/{option.unit or 'шт'}")
        return "\n".join(lines)

    matches = _match_items(items, colors=colors, desired_text=desired_text)
    if not matches:
        return "По наличию на сегодня нет явно подходящих позиций под запрос. Не обещай конкретные цветы без уточнения."

    lines = ["По наличию на сегодня релевантно:"]
    for item in matches[:8]:
        if item.status == StockStatus.UNAVAILABLE:
            lines.append(f"- {item.name} — нет")
        else:
            price = f", {item.price} ₽/{item.unit or 'шт'}" if item.price is not None else ""
            lines.append(f"- {item.name} — {item.quantity_text}{price}")
    return "\n".join(lines)


def _extract_quantity_number(text: str) -> int | None:
    match = re.search(r"\b(\d+)\b", text)
    return int(match.group(1)) if match else None


def _status_from_quantity(text: str, quantity_number: int | None) -> StockStatus:
    if re.search(r"\b0\b", text) or any(word in text for word in ("нет", "законч", "отсутств")):
        return StockStatus.UNAVAILABLE
    if any(word in text for word in ("мало", "чуть", "немного")):
        return StockStatus.LOW
    if quantity_number == 0:
        return StockStatus.UNAVAILABLE
    return StockStatus.AVAILABLE


def _match_items(items: list[StockItem], *, colors: list[str], desired_text: str) -> list[StockItem]:
    query = f"{desired_text.lower()} {' '.join(colors).lower()}".replace("ё", "е")
    scored: list[tuple[int, StockItem]] = []
    for item in items:
        normalized_name = item.name.lower().replace("ё", "е")
        score = 0
        for token in re.findall(r"[а-яa-z]+", query):
            stem = token[:6]
            color_stem = token[:3]
            if len(token) >= 4 and (token in normalized_name or stem in normalized_name or color_stem in normalized_name):
                score += 1
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


def select_budget_options(
    items: list[StockItem],
    *,
    desired_text: str,
    composition_units: tuple[str, ...],
    sensitive_occasion: bool = False,
    sensitive_forbidden_words: tuple[str, ...] = (),
    budget_ceiling: int | None = None,
    min_options: int = 2,
) -> BudgetOptions:
    unit_set = {unit.lower().replace("ё", "е") for unit in composition_units}
    forbidden = [word.lower().replace("ё", "е") for word in sensitive_forbidden_words] if sensitive_occasion else []
    raw_candidates: list[StockItem] = []
    for item in items:
        unit = (item.unit or "").lower().replace("ё", "е")
        if unit not in unit_set:
            continue
        if item.status == StockStatus.UNAVAILABLE or item.quantity_number == 0:
            continue
        if item.price is None:
            continue
        raw_candidates.append(item)
    if budget_ceiling is not None:
        raw_candidates = [item for item in raw_candidates if item.price is not None and item.price <= budget_ceiling]
    raw_candidates.sort(key=lambda item: item.price or 0)
    if not forbidden:
        candidates = raw_candidates
    else:
        candidates = []
        for item in raw_candidates:
            name = item.name.lower().replace("ё", "е")
            if any(re.search(rf"\b{re.escape(word)}\w*\b", name) for word in forbidden):
                continue
            candidates.append(item)
        if len(candidates) < min_options and len(raw_candidates) >= min_options:
            # For sensitive occasions, do not leak forbidden names. Keep safe price levels
            # from real catalog compositions so the reply can offer a choice without names.
            return BudgetOptions(_to_budget_options(_select_three(raw_candidates)), hide_names=True)
    if len(candidates) < min_options:
        return BudgetOptions([])
    selected = candidates[-3:] if budget_ceiling is not None else _select_three(candidates)
    return BudgetOptions(_to_budget_options(selected))
def _to_budget_options(items: list[StockItem]) -> list[BudgetOption]:
    return [BudgetOption(name=item.name, price=item.price or 0, unit=item.unit, image_path=item.image_path) for item in items if item.price is not None]


def _select_three(candidates: list[StockItem]) -> list[StockItem]:
    if len(candidates) <= 3:
        return candidates
    return [candidates[0], candidates[(len(candidates)-1)//2], candidates[-1]]
