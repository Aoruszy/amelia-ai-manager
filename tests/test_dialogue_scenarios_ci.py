from __future__ import annotations

from amelia_manager.dialogue_eval import build_default_scenarios
from amelia_manager.live_scenarios import build_live_scenarios


def test_default_and_live_scenario_ids_are_unique():
    scenarios = build_default_scenarios() + build_live_scenarios()
    ids = [scenario.id for scenario in scenarios]
    duplicates = sorted({scenario_id for scenario_id in ids if ids.count(scenario_id) > 1})

    assert duplicates == []
