import json

import pytest

from amelia_manager.dialogue_eval import DialogueScenario, build_default_scenarios, run_dialogue_eval, write_dialogue_eval_report


@pytest.mark.asyncio
async def test_dialogue_eval_suite_has_curated_coverage_and_passes_checklists():
    scenarios = build_default_scenarios()

    assert len(scenarios) >= 30
    assert {scenario.category for scenario in scenarios} >= {
        "greeting",
        "order_flow",
        "pickup",
        "delivery",
        "risk_handoff",
        "media",
        "stock",
        "stale_state",
    }

    report = await run_dialogue_eval(scenarios)

    assert report["summary"]["total"] == len(scenarios)
    assert report["summary"]["failed"] == 0
    assert all(item["passed"] for item in report["results"])
    assert all("checks" in item for item in report["results"])


@pytest.mark.asyncio
async def test_dialogue_eval_report_is_machine_readable_json(tmp_path):
    output_path = tmp_path / "dialogue_eval_report.json"

    report = await write_dialogue_eval_report(output_path)

    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded == report
    assert loaded["summary"]["total"] >= 30
    assert loaded["summary"]["failed"] == 0
    assert {"id", "category", "passed", "checks", "output"}.issubset(loaded["results"][0])


class CountingLiveLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        return "Подскажите, пожалуйста, бюджет."


class StructuredConfidenceLLM:
    async def generate(self, prompt: str) -> str:
        return json.dumps(
            {
                "reply": "Подскажите, пожалуйста, бюджет.",
                "intent": "order",
                "next_step": "ask_budget",
                "confidence": 0.82,
                "needs_human": False,
                "case_patch": {},
            },
            ensure_ascii=False,
        )


@pytest.mark.asyncio
async def test_live_dialogue_eval_uses_llm_and_caches_raw_replies(tmp_path):
    cache_path = tmp_path / "live_cache.json"
    llm = CountingLiveLLM()
    scenarios = [
        DialogueScenario(
            "live-budget-question",
            "order_flow",
            ["Клиент: Нужен букет"],
            must_contain=("бюджет",),
        )
    ]

    first = await run_dialogue_eval(scenarios, llm=llm, cache_path=cache_path)
    second = await run_dialogue_eval(scenarios, llm=llm, cache_path=cache_path)

    assert first["summary"]["failed"] == 0
    assert second["summary"]["failed"] == 0
    assert llm.calls == 1
    assert json.loads(cache_path.read_text(encoding="utf-8"))["live-budget-question"] == "Подскажите, пожалуйста, бюджет."


@pytest.mark.asyncio
async def test_dialogue_eval_summary_includes_confidence_distribution():
    report = await run_dialogue_eval(
        [DialogueScenario("confidence-case", "order_flow", ["Клиент: Нужен букет"], expected_next_step="ask_budget")],
        llm=StructuredConfidenceLLM(),
        use_cache=False,
    )

    assert report["summary"]["confidence_distribution"]["0.7-1.0"] == 1
    assert report["results"][0]["confidence"] == 0.82
