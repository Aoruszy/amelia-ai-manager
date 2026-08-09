import httpx
import pytest

from amelia_manager.llm_client import GeminiClient


@pytest.mark.asyncio
async def test_gemini_api_key_is_sent_in_header_not_url_query():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
            request=request,
        )

    client = GeminiClient(
        api_key="test-secret-key",
        model="gemini-test",
        transport=httpx.MockTransport(handler),
    )

    assert await client.generate("hello") == "ok"
    request = requests[0]

    assert "key=" not in str(request.url)
    assert request.headers["x-goog-api-key"] == "test-secret-key"
