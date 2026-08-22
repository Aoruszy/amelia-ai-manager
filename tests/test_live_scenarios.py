import pytest

from amelia_manager import dialogue_eval
from amelia_manager.dialogue_eval import build_default_scenarios
from amelia_manager.live_scenarios import build_live_scenarios
from amelia_manager.risk import RiskLevel


class StaticLLM:
    async def generate(self, prompt: str) -> str:
        return "Поняла. Подскажите, пожалуйста, недостающие детали заказа?"


def test_build_live_scenarios_contains_real_case_catalog():
    scenarios = build_live_scenarios()

    assert len(scenarios) == 42
    ids = [scenario.id for scenario in scenarios]
    assert len(ids) == len(set(ids))
    assert {
        "real-march-8-rollover",
        "real-pickup-no-address",
        "real-complex-delivery-address",
        "real-budget-correction",
        "real-deferred-date-confirmed-moves-on",
        "real-pickup-to-delivery-reset",
        "real-sender-recipient-roles",
        "real-known-sender-not-reasked",
        "real-second-order-reset",
        "real-stock-unavailable-pions",
        "real-stock-empty-no-promise",
        "real-roses-guarantee-no-promise",
        "real-discount-medium-continues",
        "real-complaint-refund-high",
        "real-corporate-high",
        "real-late-out-of-city-medium",
        "real-human-manager-request",
        "real-prompt-injection-clean",
        "real-payment-confirmation-risk",
        "real-gibberish-stable",
        "real-funeral-wreath-sensitive",
        "real-complaint-with-product-name",
        "real-payment-claim-with-product-name",
        "real-sensitive-client-uses-forbidden-word",
        "real-sensitive-no-upsell-offer",
        "real-upsell-not-repeated-after-offer",
        "real-pickup-outside-shop-hours",
        "real-pickup-summary-without-payment-and-recipient",
        "real-all-in-one-no-rereask",
        "real-grouped-when-where-complete",
        "real-grouped-when-where-partial-date",
        "real-grouped-contacts-both-roles",
        "real-grouped-pickup-one-phrase",
        "real-identity-question",
        "real-price-objection-no-discount",
        "real-bouquet-price-no-exact-quote",
        "real-delivery-price-is-known-fact",
        "real-stage3-2-offer-budget-options-by-default",
        "real-stage3-2-client-chooses-middle-option",
        "real-stage3-2-client-rejects-all-options",
        "real-stage3-2-date-after-options-is-not-option-choice",
        "real-stage3-2-sensitive-with-catalog-keeps-cautious-reply",
    } == set(ids)
    assert any(s.expected_risk == RiskLevel.HIGH for s in scenarios)
    assert any(s.expected_risk == RiskLevel.MEDIUM for s in scenarios)
    assert any(s.stock_context for s in scenarios)


def test_live_scenarios_encode_hard_safety_expectations():
    scenarios = {scenario.id: scenario for scenario in build_live_scenarios()}

    assert scenarios["real-prompt-injection-clean"].must_not_contain == (
        "бизнес-правила профиля",
        "правила стиля",
    )
    assert "точно есть" in scenarios["real-stock-unavailable-pions"].must_not_contain
    assert "в наличии" in scenarios["real-stock-empty-no-promise"].must_not_contain
    assert "ярк" in scenarios["real-funeral-wreath-sensitive"].must_not_contain
    assert scenarios["real-discount-medium-continues"].expected_kind == "send"
    assert scenarios["real-complaint-refund-high"].expected_kind == "human_takeover"
    assert scenarios["real-corporate-high"].expected_kind == "human_takeover"


def test_live_mode_appends_real_scenarios_to_default_set(monkeypatch, tmp_path):
    captured = {}

    async def fake_write_report(path, scenarios=None, **kwargs):
        captured["ids"] = [scenario.id for scenario in scenarios]
        return {
            "summary": {"total": len(scenarios), "passed": len(scenarios), "failed": 0, "pass_rate": 1.0},
            "results": [],
        }

    class FakeSettings:
        llm_api_key = "test-key"
        llm_provider = "openai"
        llm_model = "test-model"
        llm_base_url = None
        llm_max_output_tokens = 1000

    monkeypatch.setattr(dialogue_eval, "Settings", FakeSettings)
    monkeypatch.setattr(dialogue_eval, "build_llm_client", lambda **kwargs: StaticLLM())
    monkeypatch.setattr(dialogue_eval, "write_dialogue_eval_report", fake_write_report)

    dialogue_eval.main(["--live", "--output", str(tmp_path / "report.json")])

    assert len(captured["ids"]) == len(build_default_scenarios()) + len(build_live_scenarios())
    assert "real-march-8-rollover" in captured["ids"]
    assert "greeting-basic" in captured["ids"]


@pytest.mark.asyncio
async def test_live_scenarios_run_through_deterministic_pipeline_without_errors():
    report = await dialogue_eval.run_dialogue_eval(build_live_scenarios(), llm=StaticLLM(), use_cache=False)

    assert report["summary"]["total"] == 42
    assert all("llm_called" in result for result in report["results"])


@pytest.mark.asyncio
async def test_live_eval_summary_does_not_report_unmeasured_stage3_1_turns_metric():
    report = await dialogue_eval.run_dialogue_eval(build_live_scenarios(), llm=StaticLLM(), use_cache=False)

    assert "stage3_1_turns_to_request" not in report["summary"]
