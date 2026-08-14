import pytest

from amelia_manager.order_extractor import extract_order_state_with_llm


class FakeLLM:
    def __init__(self, response: str):
        self.response = response

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return self.response


@pytest.mark.asyncio
async def test_extract_order_state_with_llm_parses_json_fields():
    state = await extract_order_state_with_llm(
        FakeLLM('{"budget": 5000, "fulfillment_type": "pickup", "delivery_time": "18:00", "payment_method": "transfer"}'),
        ["Клиент: заберу сам ближе к шести, оплачу переводом"],
    )

    assert state.budget == 5000
    assert state.fulfillment_type == "pickup"
    assert state.delivery_time == "18:00"
    assert state.payment_method == "transfer"


@pytest.mark.asyncio
async def test_extract_order_state_with_llm_falls_back_to_regex_on_bad_json():
    state = await extract_order_state_with_llm(FakeLLM('не json'), ["Клиент: 5000", "Клиент: Самовывоз"])

    assert state.budget == 5000
    assert state.fulfillment_type == "pickup"
