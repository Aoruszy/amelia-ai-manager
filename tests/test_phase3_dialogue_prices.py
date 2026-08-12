from amelia_manager.conversation_engine import ConversationEngine
from amelia_manager.dialogue_eval import DialogueScenario, _check_no_invented_numbers
from amelia_manager.company_profile import load_company_profile
from amelia_manager.llm_client import LLMError
from amelia_manager.risk import RiskLevel
import pytest


class FailingLLM:
    async def generate(self, prompt: str, **kwargs):
        raise LLMError("force deterministic/cautious path")


@pytest.mark.asyncio
async def test_catalog_price_question_gets_price_from_stock_context():
    engine = ConversationEngine(FailingLLM())

    action = await engine.handle_messages(
        client_summary="Eval",
        recent_messages=["Клиент: сколько стоят пионы?"],
        stage="eval",
        stock_context="По наличию на сегодня релевантно:\n- пионы — 12, 4500 ₽/шт",
    )

    assert action.kind == "send"
    assert "4500" in action.messages[0]
    assert action.risk_level == RiskLevel.MEDIUM


def test_eval_no_invented_numbers_allows_catalog_prices_from_stock_context():
    scenario = DialogueScenario(
        id="catalog-price",
        category="stock",
        recent_messages=["Клиент: сколько стоят пионы?"],
        stock_context="По наличию на сегодня релевантно:\n- пионы — 12, 4500 ₽/шт",
    )

    check = _check_no_invented_numbers("Пионы 4500 ₽ за штуку", scenario=scenario, company_profile=load_company_profile())

    assert check["passed"] is True


@pytest.mark.asyncio
async def test_catalog_missing_price_does_not_invent_price():
    engine = ConversationEngine(FailingLLM())

    action = await engine.handle_messages(
        client_summary="Eval",
        recent_messages=["Клиент: сколько стоят пионы?"],
        stage="eval",
        stock_context="По наличию на сегодня релевантно:\n- пионы — 12",
    )

    assert "уточ" in action.messages[0].lower()
    assert "4500" not in action.messages[0]


@pytest.mark.asyncio
async def test_bouquet_cost_question_gets_catalog_range_not_exact_single_price():
    engine = ConversationEngine(FailingLLM())

    action = await engine.handle_messages(
        client_summary="Eval",
        recent_messages=["Клиент: сколько выйдет букет с пионами?"],
        stage="eval",
        stock_context="По наличию на сегодня релевантно:\n- пионы — 12, 4500 ₽/шт",
    )

    reply = action.messages[0].lower()
    assert "примерно" in reply
    assert "4000" in reply
    assert "4500" in reply
    assert "итог" in reply and "менеджер" in reply
    assert "4500 ₽/шт" not in reply
