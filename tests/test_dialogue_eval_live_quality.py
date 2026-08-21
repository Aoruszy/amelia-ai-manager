import json

import pytest

from amelia_manager import dialogue_eval
from amelia_manager.dialogue_eval import DialogueScenario, run_dialogue_eval, write_dialogue_eval_report
from amelia_manager.order_card import OrderCard


class CountingLLM:
    def __init__(self, reply: str = "Поняла. Подскажите, пожалуйста, какой бюджет рассматриваете?") -> None:
        self.calls = 0
        self.reply = reply

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        return self.reply


@pytest.mark.asyncio
async def test_live_eval_marks_only_scenarios_that_reached_llm(tmp_path):
    llm = CountingLLM()
    report = await run_dialogue_eval(
        [
            DialogueScenario("short-greeting", "greeting", ["Клиент: Здравствуйте"]),
            DialogueScenario("llm-budget", "order_flow", ["Клиент: Нужен букет"]),
        ],
        llm=llm,
        cache_path=tmp_path / "cache.json",
    )

    by_id = {result["id"]: result for result in report["results"]}
    assert by_id["short-greeting"]["llm_called"] is False
    assert by_id["llm-budget"]["llm_called"] is True
    assert report["summary"]["live_only"] == {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "pass_rate": 1.0,
    }
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_live_eval_no_cache_forces_model_call_and_does_not_write_cache(tmp_path):
    cache_path = tmp_path / "live_cache.json"
    cache_path.write_text(json.dumps({"llm-budget": "cached reply"}, ensure_ascii=False), encoding="utf-8")
    llm = CountingLLM("Подскажите бюджет, пожалуйста.")

    report = await run_dialogue_eval(
        [DialogueScenario("llm-budget", "order_flow", ["Клиент: Нужен букет"])],
        llm=llm,
        cache_path=cache_path,
        use_cache=False,
    )

    assert llm.calls == 1
    assert report["results"][0]["output"] == "Подскажите бюджет, пожалуйста."
    assert json.loads(cache_path.read_text(encoding="utf-8"))["llm-budget"] == "cached reply"


@pytest.mark.asyncio
async def test_live_eval_structural_checks_do_not_require_exact_wording():
    llm = CountingLLM("Для начала подскажите, пожалуйста, сумму, на которую ориентируемся.")

    report = await run_dialogue_eval(
        [
            DialogueScenario(
                "semantic-budget-question",
                "order_flow",
                ["Клиент: Нужен букет"],
                expected_next_step="ask_budget",
            )
        ],
        llm=llm,
    )

    assert report["summary"]["failed"] == 0
    check_names = {check["name"] for check in report["results"][0]["checks"]}
    assert {"single_question", "reply_length", "safety_clean", "next_step_advanced"}.issubset(check_names)


@pytest.mark.asyncio
async def test_live_eval_safety_fallback_records_invented_numbers_without_leaking_them():
    card = OrderCard(budget=5000, colors=["розы"], fulfillment_type="delivery", address="ул. Тестовая 1")
    llm = CountingLLM("Какой бюджет? Доставка будет 9999 рублей?")

    report = await run_dialogue_eval(
        [
            DialogueScenario(
                "bad-repeat-and-number",
                "order_flow",
                ["Клиент: продолжим"],
                order_card=card,
            )
        ],
        llm=llm,
    )

    result = report["results"][0]
    checks = {check["name"]: check for check in result["checks"]}
    assert "9999" not in result["output"]
    assert result["safety_triggered_reasons"]
    assert result["safety_retry_succeeded"] is False
    assert checks["no_invented_numbers"]["passed"] is True


@pytest.mark.asyncio
async def test_live_eval_allows_numbers_from_recent_messages():
    llm = CountingLLM("Можно собрать в пределах 3000 ₽. Какие оттенки нравятся?")

    report = await run_dialogue_eval(
        [DialogueScenario("known-input-number", "order_flow", ["Клиент: букет маме до 3000"] )],
        llm=llm,
        use_cache=False,
    )

    checks = {check["name"]: check for check in report["results"][0]["checks"]}
    assert checks["no_invented_numbers"]["passed"] is True


@pytest.mark.asyncio
async def test_live_eval_report_records_model_name(tmp_path):
    output_path = tmp_path / "report.json"
    report = await write_dialogue_eval_report(
        output_path,
        [DialogueScenario("llm-budget", "order_flow", ["Клиент: Нужен букет"])],
        llm=CountingLLM(),
        model_name="test-model",
    )

    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded == report
    assert loaded["model"] == "test-model"
    assert loaded["results"][0]["llm_called"] is True


def test_live_cli_returns_zero_and_prints_failures(monkeypatch, tmp_path, capsys):
    class FakeSettings:
        llm_api_key = "test-key"
        llm_provider = "openai"
        llm_model = "test-model"
        llm_base_url = None
        llm_max_output_tokens = 1000

    async def fake_write_report(*args, **kwargs):
        return {
            "summary": {"total": 1, "passed": 0, "failed": 1, "pass_rate": 0.0},
            "results": [
                {
                    "id": "bad-live-case",
                    "category": "order_flow",
                    "passed": False,
                    "checks": [{"name": "safety_clean", "passed": False, "details": {}}],
                }
            ],
        }

    monkeypatch.setattr(dialogue_eval, "Settings", FakeSettings)
    monkeypatch.setattr(dialogue_eval, "build_llm_client", lambda **kwargs: CountingLLM())
    monkeypatch.setattr(dialogue_eval, "write_dialogue_eval_report", fake_write_report)

    dialogue_eval.main(["--live", "--output", str(tmp_path / "report.json")])

    out = capsys.readouterr().out
    assert "Live eval failures" in out
    assert "bad-live-case" in out
