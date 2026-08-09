import httpx
import pytest

from amelia_manager.llm_client import GeminiClient, LLMError


@pytest.mark.asyncio
async def test_gemini_client_extracts_text_from_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "key=" not in str(request.url)
        assert request.headers["x-goog-api-key"] == "test-key"
        body = request.read().decode()
        assert "Привет" in body
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "Здравствуйте 🙂"}]}}
                ]
            },
        )

    client = GeminiClient(api_key="test-key", model="gemini-test", transport=httpx.MockTransport(handler))

    assert await client.generate("Привет") == "Здравствуйте 🙂"


@pytest.mark.asyncio
async def test_gemini_client_raises_safe_error_without_key_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "bad key test-key"}})

    client = GeminiClient(api_key="test-key", model="gemini-test", transport=httpx.MockTransport(handler))

    with pytest.raises(LLMError) as exc:
        await client.generate("Привет")

    assert "test-key" not in str(exc.value)
    assert "Gemini request failed" in str(exc.value)
