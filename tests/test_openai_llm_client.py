import httpx
import pytest
import json

from amelia_manager.llm_client import LLMError, OpenAIResponsesClient


@pytest.mark.asyncio
async def test_openai_responses_client_uses_responses_api_and_model():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"output_text": "Здравствуйте"})

    client = OpenAIResponsesClient(
        api_key="test-key",
        model="gpt-5.6-luna",
        transport=httpx.MockTransport(handler),
    )

    assert await client.generate("Привет") == "Здравствуйте"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["authorization"] == "Bearer test-key"
    assert '"model":"gpt-5.6-luna"' in captured["body"]
    assert '"input":"Привет"' in captured["body"]


@pytest.mark.asyncio
async def test_openai_responses_client_requests_json_object_when_schema_requested():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"output_text": '{"reply":"ok"}'})

    client = OpenAIResponsesClient(api_key="test-key", model="gpt-5.6-luna", transport=httpx.MockTransport(handler))

    await client.generate(
        "Верни JSON",
        response_mime_type="application/json",
        response_schema={"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]},
    )

    assert '"text"' in captured["body"]
    assert '"format"' in captured["body"]
    assert '"json_schema"' in captured["body"]
    assert '"schema"' in captured["body"]


@pytest.mark.asyncio
async def test_openai_responses_client_sends_image_data_urls_as_input_images():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read().decode())
        return httpx.Response(200, json={"output_text": '{"reply":"ok"}'})

    client = OpenAIResponsesClient(api_key="test-key", model="gpt-5.6-luna", transport=httpx.MockTransport(handler))

    await client.generate(
        "Опиши букет",
        response_mime_type="application/json",
        response_schema={"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]},
        image_data_urls=["data:image/jpeg;base64,abc"],
    )

    content = captured["body"]["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "Опиши букет"}
    assert content[1] == {"type": "input_image", "image_url": "data:image/jpeg;base64,abc"}
    assert captured["body"]["text"]["format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_openai_responses_client_reports_max_output_token_incomplete_separately():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [],
            },
        )

    client = OpenAIResponsesClient(api_key="test-key", model="gpt-5.6-luna", transport=httpx.MockTransport(handler))

    with pytest.raises(LLMError, match="incomplete.*max_output_tokens"):
        await client.generate("Верни JSON")
