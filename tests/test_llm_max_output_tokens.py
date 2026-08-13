from amelia_manager.llm_client import GeminiClient, OpenAIResponsesClient


def test_gemini_client_uses_configured_max_output_tokens():
    client = GeminiClient(api_key="key", model="gemini", max_output_tokens=1000)

    assert client.max_output_tokens == 1000


def test_openai_client_uses_configured_max_output_tokens():
    client = OpenAIResponsesClient(api_key="key", model="gpt", max_output_tokens=1000)

    assert client.max_output_tokens == 1000
