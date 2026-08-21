from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from amelia_manager.config import Settings
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.company_profile import CompanyProfile, load_company_profile
from amelia_manager.llm_client import LLMError, build_llm_client
from amelia_manager.order_card import OrderCard
from amelia_manager.order_policy import get_next_step
from amelia_manager.order_state import OrderState, extract_order_state
from amelia_manager.risk import RiskLevel
from amelia_manager.safety import check_reply_safety


class DeterministicEvalLLM:
    def __init__(self) -> None:
        self.called = False

    async def generate(self, prompt: str) -> str:
        self.called = True
        raise LLMError("dialogue eval uses deterministic fallback")


class CachedEvalLLM:
    def __init__(self, llm: Any, *, scenario_id: str, cache: dict[str, str], use_cache: bool = True) -> None:
        self.llm = llm
        self.scenario_id = scenario_id
        self.cache = cache
        self.use_cache = use_cache
        self.called = False

    async def generate(self, prompt: str) -> str:
        self.called = True
        if self.use_cache and self.scenario_id in self.cache:
            return self.cache[self.scenario_id]
        reply = await self.llm.generate(prompt)
        if self.use_cache:
            self.cache[self.scenario_id] = reply
        return reply


@dataclass(frozen=True)
class DialogueScenario:
    id: str
    category: str
    recent_messages: list[str]
    expected_kind: str = "send"
    expected_risk: RiskLevel = RiskLevel.LOW
    order_card: OrderCard | None = None
    stock_context: str | None = None
    must_contain: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()
    expect_admin_ready: bool | None = None
    require_safe: bool = True
    allow_multiple_questions: bool = False
    expected_next_step: str | None = None
    structural_checks: tuple[str, ...] = ()
    notes: str = ""


async def run_dialogue_eval(
    scenarios: list[DialogueScenario] | None = None,
    *,
    llm: Any | None = None,
    cache_path: str | Path | None = None,
    use_cache: bool = True,
    model_name: str | None = None,
    company_profile: CompanyProfile | None = None,
) -> dict[str, Any]:
    cases = scenarios or build_default_scenarios()
    profile = company_profile or load_company_profile("amelia_flowers")
    cache = _load_cache(cache_path) if use_cache else {}
    results = []
    for scenario in cases:
        scenario_llm = CachedEvalLLM(llm, scenario_id=scenario.id, cache=cache, use_cache=use_cache) if llm is not None else DeterministicEvalLLM()
        engine = ConversationEngine(scenario_llm, company_profile=profile)
        action = await engine.handle_messages(
            client_summary="Eval клиент",
            recent_messages=scenario.recent_messages,
            stage="eval",
            stock_context=scenario.stock_context,
            order_card=scenario.order_card,
        )
        output = "\n".join(action.messages)
        checks = _evaluate_checks(
            scenario,
            kind=action.kind,
            risk_level=action.risk_level,
            output=output,
            company_profile=profile,
        )
        results.append(
            {
                "id": scenario.id,
                "category": scenario.category,
                "passed": all(check["passed"] for check in checks),
                "checks": checks,
                "kind": action.kind,
                "risk_level": action.risk_level.value,
                "risk_category": action.risk_category.value if action.risk_category else None,
                "output": output,
                "llm_called": scenario_llm.called,
                "intent": action.intent,
                "next_step": action.next_step,
                "confidence": action.confidence,
                "safety_reasons": action.safety_reasons,
                "safety_triggered_reasons": action.safety_triggered_reasons,
                "safety_retry_succeeded": action.safety_retry_succeeded,
                "notes": scenario.notes,
            }
        )
    if use_cache:
        _write_cache(cache_path, cache)
    failed = sum(1 for result in results if not result["passed"])
    live_results = [result for result in results if result["llm_called"]]
    live_failed = sum(1 for result in live_results if not result["passed"])
    return {
        "model": model_name,
        "summary": {
            "total": len(results),
            "passed": len(results) - failed,
            "failed": failed,
            "pass_rate": (len(results) - failed) / len(results) if results else 0.0,
            "live_only": {
                "total": len(live_results),
                "passed": len(live_results) - live_failed,
                "failed": live_failed,
                "pass_rate": (len(live_results) - live_failed) / len(live_results) if live_results else 0.0,
            },
            "confidence_distribution": _confidence_distribution(
                [result["confidence"] for result in results if isinstance(result.get("confidence"), int | float)]
            ),
        },
        "results": results,
    }


def _confidence_distribution(values: list[float]) -> dict[str, int]:
    buckets = {"0-0.5": 0, "0.5-0.7": 0, "0.7-1.0": 0}
    for value in values:
        if value < 0.5:
            buckets["0-0.5"] += 1
        elif value < 0.7:
            buckets["0.5-0.7"] += 1
        else:
            buckets["0.7-1.0"] += 1
    return buckets


async def write_dialogue_eval_report(
    path: str | Path,
    scenarios: list[DialogueScenario] | None = None,
    *,
    llm: Any | None = None,
    cache_path: str | Path | None = None,
    use_cache: bool = True,
    model_name: str | None = None,
) -> dict[str, Any]:
    report = await run_dialogue_eval(
        scenarios,
        llm=llm,
        cache_path=cache_path,
        use_cache=use_cache,
        model_name=model_name,
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _load_cache(cache_path: str | Path | None) -> dict[str, str]:
    if cache_path is None:
        return {}
    path = Path(cache_path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in data.items() if isinstance(value, str)}


def _write_cache(cache_path: str | Path | None, cache: dict[str, str]) -> None:
    if cache_path is None:
        return
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _evaluate_checks(
    scenario: DialogueScenario,
    *,
    kind: str,
    risk_level: RiskLevel,
    output: str,
    company_profile: CompanyProfile | None = None,
) -> list[dict[str, Any]]:
    normalized = output.lower().replace("ё", "е")
    profile = company_profile or load_company_profile("amelia_flowers")
    checks: list[dict[str, Any]] = [
        _check("expected_kind", kind == scenario.expected_kind, {"expected": scenario.expected_kind, "actual": kind}),
        _check(
            "expected_risk",
            risk_level == scenario.expected_risk,
            {"expected": scenario.expected_risk.value, "actual": risk_level.value},
        ),
        _check("non_empty_output", bool(output.strip()), {}),
    ]
    if scenario.require_safe:
        safety = check_reply_safety(
            output,
            stock_context=scenario.stock_context,
            company_profile=profile,
            order_card=scenario.order_card,
        )
    else:
        safety = None
    for structural_check in _structural_checks_for(scenario):
        if structural_check == "single_question":
            checks.append(
                _check(
                    "single_question",
                    scenario.allow_multiple_questions or output.count("?") <= 1,
                    {"question_count": output.count("?")},
                )
            )
        elif structural_check == "reply_length":
            max_chars = Settings().max_reply_chars
            checks.append(_check("reply_length", len(output) <= max_chars, {"length": len(output), "max": max_chars}))
        elif structural_check == "safety_clean":
            checks.append(
                _check(
                    "safety_clean",
                    safety.is_safe if safety is not None else True,
                    {"reasons": safety.reasons if safety is not None else []},
                )
            )
        elif structural_check == "no_repeat_known_field":
            checks.append(_check_no_repeat_known_field(scenario, normalized))
        elif structural_check == "no_invented_numbers":
            checks.append(_check_no_invented_numbers(output, scenario=scenario, company_profile=profile))
        elif structural_check == "next_step_advanced":
            checks.append(_check_next_step(scenario, company_profile=profile))
        elif structural_check == "no_repeated_phrase":
            checks.append(_check_no_repeated_phrase(scenario, output))
    for token in scenario.must_contain:
        checks.append(_check(f"contains:{token}", token.lower().replace("ё", "е") in normalized, {}))
    for token in scenario.must_not_contain:
        checks.append(_check(f"not_contains:{token}", token.lower().replace("ё", "е") not in normalized, {}))
    if scenario.expect_admin_ready is not None:
        checks.append(
            _check(
                "admin_request_readiness",
                bool(scenario.order_card and scenario.order_card.is_ready_for_admin_request()) == scenario.expect_admin_ready,
                {"expected": scenario.expect_admin_ready},
            )
        )
    return checks


def _structural_checks_for(scenario: DialogueScenario) -> tuple[str, ...]:
    base = ("single_question", "reply_length", "safety_clean", "no_repeat_known_field", "no_invented_numbers")
    if not scenario.expected_next_step:
        return base + scenario.structural_checks
    return base + scenario.structural_checks + ("next_step_advanced",)


def _check_no_repeat_known_field(scenario: DialogueScenario, normalized_output: str) -> dict[str, Any]:
    card = scenario.order_card
    if card is None:
        return _check("no_repeat_known_field", True, {})
    markers = {
        "budget": ("бюджет",),
        "address": ("адрес",),
        "sender_phone": ("ваш телефон", "ваш номер"),
        "recipient_phone": ("телефон получателя", "номер получателя"),
        "delivery_time": ("во сколько", "к какому времени"),
        "delivery_date": ("на какое число",),
    }
    repeated: list[str] = []
    for field_name, field_markers in markers.items():
        if getattr(card, field_name, None) in (None, "", [], {}):
            continue
        if any(_asks_for_marker(normalized_output, marker) for marker in field_markers):
            repeated.append(field_name)
    return _check("no_repeat_known_field", not repeated, {"repeated_fields": repeated})


def _asks_for_marker(normalized_output: str, marker: str) -> bool:
    for sentence in re.split(r"[.!\n]+", normalized_output):
        if marker not in sentence:
            continue
        if "?" in sentence or re.search(r"\b(?:подскаж\w*|уточн\w*|напиш\w*|какой|какая|какое|ваш|ваше|нужен|нужна)\b", sentence):
            return True
    return False


def _check_no_invented_numbers(output: str, *, scenario: DialogueScenario, company_profile: CompanyProfile) -> dict[str, Any]:
    numbers = set(re.findall(r"\d{3,}", output))
    if not numbers:
        return _check("no_invented_numbers", True, {})
    allowed_text = " ".join(
        str(part)
        for part in (
            scenario.order_card.to_dict() if scenario.order_card else {},
            "\n".join(scenario.recent_messages),
            _scenario_order_state(scenario).__dict__,
            scenario.stock_context or "",
            company_profile.free_delivery_from or "",
            company_profile.delivery_city_price or "",
            company_profile.shop_hours or "",
            company_profile.delivery_hours or "",
            company_profile.public_phone or "",
            company_profile.pickup_address or "",
            " ".join(str(offer.price) for offer in company_profile.upsell_offers if offer.price is not None),
            _spoken_number_equivalents("\n".join(scenario.recent_messages)),
        )
    )
    invented = sorted(number for number in numbers if number not in allowed_text)
    return _check("no_invented_numbers", not invented, {"invented_numbers": invented})


def _check_no_repeated_phrase(scenario: DialogueScenario, output: str) -> dict[str, Any]:
    previous_bot = _last_bot_message(scenario.recent_messages)
    if not previous_bot:
        return _check("no_repeated_phrase", True, {})
    previous_start = _normalized_prefix(previous_bot, length=40)
    output_text = _normalized_prefix(output, length=80)
    repeated = bool(previous_start and previous_start in output_text)
    return _check("no_repeated_phrase", not repeated, {"previous_prefix": previous_start})


def _last_bot_message(messages: list[str]) -> str | None:
    for message in reversed(messages):
        lowered = message.lower().strip()
        if lowered.startswith("менеджер:") or lowered.startswith("алина:"):
            return re.sub(r"^(?:менеджер|алина):\s*", "", message, flags=re.IGNORECASE).strip()
    return None


def _normalized_prefix(text: str, *, length: int) -> str:
    normalized = re.sub(r"[^0-9a-zа-я]+", " ", text.lower().replace("ё", "е"))
    return re.sub(r"\s+", " ", normalized).strip()[:length].strip()


def _check_next_step(scenario: DialogueScenario, *, company_profile: CompanyProfile) -> dict[str, Any]:
    if scenario.expected_next_step is None:
        return _check("next_step_advanced", True, {})
    state = _scenario_order_state(scenario)
    actual = get_next_step(state, company_profile=company_profile).code
    return _check(
        "next_step_advanced",
        actual == scenario.expected_next_step,
        {"expected": scenario.expected_next_step, "actual": actual},
    )


_SPOKEN_BUDGETS = {
    "одну": 1000,
    "один": 1000,
    "две": 2000,
    "два": 2000,
    "три": 3000,
    "четыре": 4000,
    "пять": 5000,
    "пяти": 5000,
    "шесть": 6000,
    "шести": 6000,
    "семь": 7000,
    "семи": 7000,
    "восемь": 8000,
    "девять": 9000,
    "десять": 10000,
}


def _spoken_number_equivalents(text: str) -> str:
    normalized = text.lower().replace("ё", "е")
    if not any(marker in normalized for marker in ("тысяч", "тыс", "к")):
        return ""
    values = [str(value) for word, value in _SPOKEN_BUDGETS.items() if re.search(rf"\b{re.escape(word)}\b", normalized)]
    return " ".join(values)


def _scenario_order_state(scenario: DialogueScenario) -> OrderState:
    if scenario.order_card is None:
        return extract_order_state(scenario.recent_messages)
    data = scenario.order_card.to_dict()
    data.pop("admin_request_sent", None)
    data.pop("client_summary_sent", None)
    data.pop("sheet_row_written", None)
    return OrderState(**data)


def _check(name: str, passed: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": passed, "details": details}


def build_default_scenarios() -> list[DialogueScenario]:
    ready_pickup = OrderCard(
        budget=5000,
        colors=["белый", "нежный"],
        fulfillment_type="pickup",
        delivery_date="today",
        delivery_time="18:00",
        sender_name="Даниил",
        sender_phone="89990000001",
    )
    ready_delivery = OrderCard(
        budget=7000,
        colors=["розовый"],
        fulfillment_type="delivery",
        delivery_date="tomorrow",
        delivery_time="12:00",
        address="ул. Тестовая, 1",
        sender_name="Даниил",
        sender_phone="89990000002",
        recipient_name="Анна",
        recipient_phone="89990000003",
        payment_method="transfer",
    )
    summarized = OrderCard.from_dict({**ready_pickup.to_dict(), "client_summary_sent": True})
    delivery_without_contacts = OrderCard(
        budget=5000,
        colors=["нежный"],
        fulfillment_type="delivery",
        delivery_date="tomorrow",
        delivery_time="15:00",
        address="ул. Гайдара 173",
    )

    return [
        DialogueScenario("greeting-basic", "greeting", ["Клиент: Здравствуйте"], must_not_contain=("доставка", "бюджет")),
        DialogueScenario("greeting-hi", "greeting", ["Клиент: Привет"], must_not_contain=("самовывоз",)),
        DialogueScenario("photo-only", "media", ["Клиент: [photo]"]),
        DialogueScenario("generic-media", "media", ["Клиент: [media]"], must_not_contain=("не могу",)),
        DialogueScenario("ask-budget-new-order", "order_flow", ["Клиент: Нужен букет девушке сегодня"], must_not_contain=("адрес", "получателя"), expected_next_step="ask_budget"),
        DialogueScenario("ask-style-after-budget", "order_flow", ["Клиент: нужен букет", "Менеджер: Подскажите бюджет", "Клиент: 5000"], must_not_contain=("доставка или самовывоз",), expected_next_step="ask_bouquet_preferences"),
        DialogueScenario("ask-fulfillment-after-style", "order_flow", ["Клиент: Букет до 5000", "Клиент: Нежный кремовый"], expected_next_step="ask_fulfillment_type"),
        DialogueScenario("ask-date-after-pickup", "pickup", ["Клиент: 5000 нежный", "Клиент: самовывоз"], must_not_contain=("получателя", "адрес доставки"), expected_next_step="ask_date"),
        DialogueScenario("ask-pickup-time", "pickup", ["Клиент: 5000 нежный самовывоз сегодня"], must_contain=("сергеева",), must_not_contain=("получателя",)),
        DialogueScenario("pickup-time-outside-hours", "pickup", ["Клиент: 5000 нежный самовывоз сегодня в 22:30"], must_contain=("09:00", "20:00"), notes="Детерминированная runtime-ветка: часы магазина берём из профиля и подставляем названное клиентом время."),
        DialogueScenario("pickup-ready-summary", "pickup", ["Клиент: всё указал"], order_card=ready_pickup, must_contain=("итог заказа", "самовывоз", "5000"), expect_admin_ready=True),
        DialogueScenario("thanks-after-summary", "pickup", ["Клиент: Спасибо"], order_card=summarized, expect_admin_ready=True),
        DialogueScenario("ask-delivery-time", "delivery", ["Клиент: 5000 нежный доставка завтра"], must_not_contain=("самовывоз",), expected_next_step="ask_delivery_time"),
        DialogueScenario("ask-delivery-address", "delivery", ["Клиент: 5000 нежный доставка завтра 15:00"], expected_next_step="ask_delivery_address"),
        DialogueScenario("ask-sender-before-recipient", "delivery", ["Клиент: 5000 нежный доставка завтра 15:00", "Клиент: Доставка на ул. Гайдара 173"], order_card=delivery_without_contacts, expected_next_step="ask_upsell"),
        DialogueScenario("ask-recipient-after-sender", "delivery", ["Клиент: 5000 нежный доставка завтра 15:00", "Клиент: Доставка на ул. Гайдара 173, Даниил 89990000002"], expected_next_step="ask_recipient_contacts"),
        DialogueScenario("delivery-ready-summary", "delivery", ["Клиент: всё указал"], order_card=ready_delivery, must_contain=("итог заказа", "доставка", "7000"), expect_admin_ready=True),
        DialogueScenario("complaint-refund-handoff", "risk_handoff", ["Клиент: Мне привезли не то, хочу возврат"], expected_kind="human_takeover", expected_risk=RiskLevel.HIGH, must_contain=("передам", "менеджеру")),
        DialogueScenario("conflict-handoff", "risk_handoff", ["Клиент: Что за бред вы мне пишете"], expected_kind="human_takeover", expected_risk=RiskLevel.HIGH, must_contain=("передам",)),
        DialogueScenario("corporate-handoff", "risk_handoff", ["Клиент: Нужен корпоративный заказ на 40 букетов"], expected_kind="human_takeover", expected_risk=RiskLevel.HIGH, must_contain=("менеджеру",)),
        DialogueScenario("discount-cautious", "risk_handoff", ["Клиент: А скидки бывают?"], expected_risk=RiskLevel.MEDIUM, must_not_contain=("подключается",)),
        DialogueScenario("out-of-city-cautious", "risk_handoff", ["Клиент: Доставка за город ночью возможна?"] , expected_risk=RiskLevel.MEDIUM),
        DialogueScenario("stock-unavailable", "stock", ["Клиент: Есть пионы?"], stock_context="По наличию на сегодня релевантно:\n- пионы — нет", expected_risk=RiskLevel.MEDIUM, must_contain=("пионы",), must_not_contain=("точно есть", "в наличии")),
        DialogueScenario("stock-unknown-cautious", "stock", ["Клиент: Есть редкие пионы в наличии?"], expected_risk=RiskLevel.MEDIUM),
        DialogueScenario("anonymous-low-risk", "order_flow", ["Клиент: Можно анонимно доставить?"], must_not_contain=("передам",), expected_next_step="ask_budget"),
        DialogueScenario("new-order-reset-generic", "stale_state", ["Клиент: Нужен букет"], must_not_contain=("старый адрес", "15000"), expect_admin_ready=False, expected_next_step="ask_budget"),
        DialogueScenario("no-stale-delivery-on-pickup", "stale_state", ["Клиент: доставка на ул. Старая", "Клиент: Нет, самовывоз, 5000 нежный сегодня"], must_not_contain=("ул. старая", "получателя"), expected_next_step="ask_pickup_time"),
        DialogueScenario("numeric-budget-context", "order_flow", ["Менеджер: Подскажите бюджет", "Клиент: 5000"], expected_next_step="ask_bouquet_preferences"),
        DialogueScenario("payment-cash-pickup-ready", "pickup", ["Клиент: всё указал"], order_card=OrderCard.from_dict({**ready_pickup.to_dict(), "payment_method": "cash"}), must_contain=("итог заказа", "на месте"), expect_admin_ready=True),
        DialogueScenario("delivery-payment-handoff-summary", "delivery", ["Клиент: всё указал"], order_card=ready_delivery, must_contain=("он подтвердит",), must_not_contain=("заказ подтвержден", "оплату зафиксировала"), expect_admin_ready=True),
        DialogueScenario("photo-with-budget-history", "media", ["Клиент: Хочу как на фото", "Клиент: [photo]"]),
        DialogueScenario("safe-please-not-complaint", "order_flow", ["Клиент: Напишите пожалуйста, букет до 5000"], expected_risk=RiskLevel.LOW, expected_next_step="ask_bouquet_preferences"),
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run dialogue-quality evals and write a JSON report.")
    parser.add_argument("--output", default="reports/dialogue_eval_report.json", help="Path to JSON report")
    parser.add_argument("--live", action="store_true", help="Run against the configured live LLM instead of deterministic fallback")
    parser.add_argument("--cache", default="reports/dialogue_eval_live_cache.json", help="Raw live LLM reply cache path")
    parser.add_argument("--no-cache", action="store_true", help="Disable live eval cache reads and writes")
    args = parser.parse_args(argv)
    llm = None
    cache_path = None
    model_name = None
    scenarios = None
    if args.live:
        from amelia_manager.live_scenarios import build_live_scenarios

        settings = Settings()
        if not settings.llm_api_key:
            raise SystemExit("LLM_API_KEY is required for --live")
        llm = build_llm_client(
            provider=settings.llm_provider,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            max_output_tokens=settings.llm_max_output_tokens,
        )
        cache_path = args.cache
        model_name = settings.llm_model
        scenarios = build_default_scenarios() + build_live_scenarios()
    report = asyncio.run(
        write_dialogue_eval_report(
            args.output,
            scenarios,
            llm=llm,
            cache_path=cache_path,
            use_cache=not args.no_cache,
            model_name=model_name,
        )
    )
    sys.stdout.write(json.dumps(report["summary"], ensure_ascii=False, indent=2) + "\n")
    if args.live and report["summary"]["failed"]:
        _print_failure_table(report)
    if report["summary"]["failed"] and not args.live:
        raise SystemExit(1)


def _print_failure_table(report: dict[str, Any]) -> None:
    failed = [result for result in report.get("results", []) if not result.get("passed")]
    if not failed:
        return
    sys.stdout.write("\nLive eval failures:\n")
    for result in failed:
        failed_checks = ", ".join(check["name"] for check in result.get("checks", []) if not check.get("passed"))
        sys.stdout.write(f"- {result.get('id')} [{result.get('category')}]: {failed_checks}\n")


if __name__ == "__main__":
    main()
