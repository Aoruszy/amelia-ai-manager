import json

import pytest

from amelia_manager.dialogue_eval import build_default_scenarios, run_dialogue_eval, write_dialogue_eval_report


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
