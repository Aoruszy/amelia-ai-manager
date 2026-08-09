from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from amelia_manager.config import Settings
from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.llm_client import GeminiClient, LLMError
from amelia_manager.order_card import OrderCard
from amelia_manager.risk import RiskLevel
from amelia_manager.safety import check_reply_safety


class DeterministicEvalLLM:
    async def generate(self, prompt: str) -> str:
        raise LLMError("dialogue eval uses deterministic fallback")


class CachedEvalLLM:
    def __init__(self, llm: Any, *, scenario_id: str, cache: dict[str, str]) -> None:
        self.llm = llm
        self.scenario_id = scenario_id
        self.cache = cache

    async def generate(self, prompt: str) -> str:
        if self.scenario_id in self.cache:
            return self.cache[self.scenario_id]
        reply = await self.llm.generate(prompt)
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
    notes: str = ""


async def run_dialogue_eval(
    scenarios: list[DialogueScenario] | None = None,
    *,
    llm: Any | None = None,
    cache_path: str | Path | None = None,
) -> dict[str, Any]:
    cases = scenarios or build_default_scenarios()
    cache = _load_cache(cache_path)
    results = []
    for scenario in cases:
        scenario_llm = CachedEvalLLM(llm, scenario_id=scenario.id, cache=cache) if llm is not None else DeterministicEvalLLM()
        engine = ConversationEngine(scenario_llm)
        action = await engine.handle_messages(
            client_summary="Eval клиент",
            recent_messages=scenario.recent_messages,
            stage="eval",
            stock_context=scenario.stock_context,
            order_card=scenario.order_card,
        )
        output = "\n".join(action.messages)
        checks = _evaluate_checks(scenario, kind=action.kind, risk_level=action.risk_level, output=output)
        results.append(
            {
                "id": scenario.id,
                "category": scenario.category,
                "passed": all(check["passed"] for check in checks),
                "checks": checks,
                "kind": action.kind,
                "risk_level": action.risk_level.value,
                "output": output,
                "notes": scenario.notes,
            }
        )
    _write_cache(cache_path, cache)
    failed = sum(1 for result in results if not result["passed"])
    return {
        "summary": {
            "total": len(results),
            "passed": len(results) - failed,
            "failed": failed,
            "pass_rate": (len(results) - failed) / len(results) if results else 0.0,
        },
        "results": results,
    }


async def write_dialogue_eval_report(
    path: str | Path,
    scenarios: list[DialogueScenario] | None = None,
    *,
    llm: Any | None = None,
    cache_path: str | Path | None = None,
) -> dict[str, Any]:
    report = await run_dialogue_eval(scenarios, llm=llm, cache_path=cache_path)
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
) -> list[dict[str, Any]]:
    normalized = output.lower().replace("ё", "е")
    checks: list[dict[str, Any]] = [
        _check("expected_kind", kind == scenario.expected_kind, {"expected": scenario.expected_kind, "actual": kind}),
        _check(
            "expected_risk",
            risk_level == scenario.expected_risk,
            {"expected": scenario.expected_risk.value, "actual": risk_level.value},
        ),
        _check("non_empty_output", bool(output.strip()), {}),
        _check("no_unsafe_promise", check_reply_safety(output).is_safe if scenario.require_safe else True, {}),
    ]
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

    return [
        DialogueScenario("greeting-basic", "greeting", ["Клиент: Здравствуйте"], must_contain=("чем могу помочь",), must_not_contain=("доставка", "бюджет")),
        DialogueScenario("greeting-hi", "greeting", ["Клиент: Привет"], must_contain=("чем могу помочь",), must_not_contain=("самовывоз",)),
        DialogueScenario("photo-only", "media", ["Клиент: [photo]"], must_contain=("вижу фото", "бюджет")),
        DialogueScenario("generic-media", "media", ["Клиент: [media]"], must_contain=("вижу вложение",), must_not_contain=("не могу",)),
        DialogueScenario("ask-budget-new-order", "order_flow", ["Клиент: Нужен букет девушке сегодня"], must_contain=("бюджет",), must_not_contain=("адрес", "получателя")),
        DialogueScenario("ask-style-after-budget", "order_flow", ["Клиент: нужен букет", "Менеджер: Подскажите бюджет", "Клиент: 5000"], must_contain=("оттенки",), must_not_contain=("доставка или самовывоз",)),
        DialogueScenario("ask-fulfillment-after-style", "order_flow", ["Клиент: Букет до 5000", "Клиент: Нежный кремовый"], must_contain=("доставка или самовывоз",)),
        DialogueScenario("ask-date-after-pickup", "pickup", ["Клиент: 5000 нежный", "Клиент: самовывоз"], must_contain=("число",), must_not_contain=("получателя", "адрес доставки")),
        DialogueScenario("ask-pickup-time", "pickup", ["Клиент: 5000 нежный самовывоз сегодня"], must_contain=("самовывозом", "сергеева"), must_not_contain=("получателя",)),
        DialogueScenario("pickup-time-outside-hours", "pickup", ["Клиент: 5000 нежный самовывоз сегодня в 22:30"], must_contain=("09:00", "20:00")),
        DialogueScenario("pickup-ready-summary", "pickup", ["Клиент: всё указал"], order_card=ready_pickup, must_contain=("итог заказа", "самовывоз", "5000"), expect_admin_ready=True),
        DialogueScenario("thanks-after-summary", "pickup", ["Клиент: Спасибо"], order_card=summarized, must_contain=("спасибо",), expect_admin_ready=True),
        DialogueScenario("ask-delivery-time", "delivery", ["Клиент: 5000 нежный доставка завтра"], must_contain=("времени",), must_not_contain=("самовывоз",)),
        DialogueScenario("ask-delivery-address", "delivery", ["Клиент: 5000 нежный доставка завтра 15:00"], must_contain=("адрес доставки",), must_not_contain=("получателя",)),
        DialogueScenario("ask-sender-before-recipient", "delivery", ["Клиент: 5000 нежный доставка завтра 15:00", "Клиент: Доставка на ул. Гайдара 173"], must_contain=("ваше имя", "телефон")),
        DialogueScenario("ask-recipient-after-sender", "delivery", ["Клиент: 5000 нежный доставка завтра 15:00", "Клиент: Доставка на ул. Гайдара 173, Даниил 89990000002"], must_contain=("получателя", "телефон")),
        DialogueScenario("delivery-ready-summary", "delivery", ["Клиент: всё указал"], order_card=ready_delivery, must_contain=("итог заказа", "доставка", "7000"), expect_admin_ready=True),
        DialogueScenario("complaint-refund-handoff", "risk_handoff", ["Клиент: Мне привезли не то, хочу возврат"], expected_kind="human_takeover", expected_risk=RiskLevel.HIGH, must_contain=("передам", "менеджеру")),
        DialogueScenario("conflict-handoff", "risk_handoff", ["Клиент: Что за бред вы мне пишете"], expected_kind="human_takeover", expected_risk=RiskLevel.HIGH, must_contain=("передам",)),
        DialogueScenario("corporate-handoff", "risk_handoff", ["Клиент: Нужен корпоративный заказ на 40 букетов"], expected_kind="human_takeover", expected_risk=RiskLevel.HIGH, must_contain=("менеджеру",)),
        DialogueScenario("discount-cautious", "risk_handoff", ["Клиент: А скидки бывают?"], expected_risk=RiskLevel.MEDIUM, must_contain=("уточню", "бюджет"), must_not_contain=("подключается",)),
        DialogueScenario("out-of-city-cautious", "risk_handoff", ["Клиент: Доставка за город ночью возможна?"], expected_risk=RiskLevel.MEDIUM, must_contain=("уточню", "куда")),
        DialogueScenario("stock-unavailable", "stock", ["Клиент: Есть пионы?"], stock_context="По наличию на сегодня релевантно:\n- пионы — нет", expected_risk=RiskLevel.MEDIUM, must_contain=("пионы", "нет")),
        DialogueScenario("stock-unknown-cautious", "stock", ["Клиент: Есть редкие пионы в наличии?"], expected_risk=RiskLevel.MEDIUM, must_contain=("наличию", "уточню")),
        DialogueScenario("anonymous-low-risk", "order_flow", ["Клиент: Можно анонимно доставить?"], must_contain=("бюджет",), must_not_contain=("передам",)),
        DialogueScenario("new-order-reset-generic", "stale_state", ["Клиент: Нужен букет"], must_contain=("бюджет",), must_not_contain=("старый адрес", "15000"), expect_admin_ready=False),
        DialogueScenario("no-stale-delivery-on-pickup", "stale_state", ["Клиент: доставка на ул. Старая", "Клиент: Нет, самовывоз, 5000 нежный сегодня"], must_contain=("самовывозом",), must_not_contain=("ул. старая", "получателя")),
        DialogueScenario("numeric-budget-context", "order_flow", ["Менеджер: Подскажите бюджет", "Клиент: 5000"], must_contain=("оттенки",), must_not_contain=("бюджет",)),
        DialogueScenario("payment-cash-pickup-ready", "pickup", ["Клиент: всё указал"], order_card=OrderCard.from_dict({**ready_pickup.to_dict(), "payment_method": "cash"}), must_contain=("итог заказа", "на месте"), expect_admin_ready=True),
        DialogueScenario("delivery-payment-handoff-summary", "delivery", ["Клиент: всё указал"], order_card=ready_delivery, must_contain=("он подтвердит",), must_not_contain=("заказ подтвержден", "оплату зафиксировала"), expect_admin_ready=True),
        DialogueScenario("photo-with-budget-history", "media", ["Клиент: Хочу как на фото", "Клиент: [photo]"], must_contain=("вижу фото", "бюджет")),
        DialogueScenario("safe-please-not-complaint", "order_flow", ["Клиент: Напишите пожалуйста, букет до 5000"], must_contain=("оттенки",), expected_risk=RiskLevel.LOW),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run dialogue-quality evals and write a JSON report.")
    parser.add_argument("--output", default="reports/dialogue_eval_report.json", help="Path to JSON report")
    parser.add_argument("--live", action="store_true", help="Run against the configured live Gemini model instead of deterministic fallback")
    parser.add_argument("--cache", default="reports/dialogue_eval_live_cache.json", help="Raw live LLM reply cache path")
    args = parser.parse_args()
    llm = None
    cache_path = None
    if args.live:
        settings = Settings()
        if not settings.llm_api_key:
            raise SystemExit("LLM_API_KEY is required for --live")
        llm = GeminiClient(api_key=settings.llm_api_key, model=settings.llm_model)
        cache_path = args.cache
    report = asyncio.run(write_dialogue_eval_report(args.output, llm=llm, cache_path=cache_path))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if report["summary"]["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
