from __future__ import annotations

import httpx
from typing import Any, Protocol


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    async def generate(
        self,
        prompt: str,
        *,
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> str: ...


class GeminiClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_output_tokens: int = 1000,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout
        self.transport = transport

    async def generate(
        self,
        prompt: str,
        *,
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.9,
                "maxOutputTokens": self.max_output_tokens,
            },
        }
        if response_mime_type:
            payload["generationConfig"]["responseMimeType"] = response_mime_type
        if response_schema:
            payload["generationConfig"]["responseSchema"] = response_schema
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            try:
                response = await client.post(url, json=payload, headers={"x-goog-api-key": self.api_key})
            except httpx.HTTPError as exc:
                raise LLMError("Gemini request failed before response") from exc

        if response.status_code >= 400:
            raise LLMError(f"Gemini request failed with HTTP {response.status_code}")

        data = response.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Gemini response did not contain text") from exc

        cleaned = text.strip()
        if not cleaned:
            raise LLMError("Gemini response was empty")
        return cleaned


class OpenAIResponsesClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        max_output_tokens: int = 1000,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout
        self.transport = transport

    async def generate(
        self,
        prompt: str,
        *,
        response_mime_type: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": prompt,
            "max_output_tokens": self.max_output_tokens,
        }
        if response_mime_type == "application/json":
            if response_schema:
                payload["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": "model_decision",
                        "schema": response_schema,
                        "strict": False,
                    }
                }
            else:
                payload["text"] = {"format": {"type": "json_object"}}

        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/responses",
                    json=payload,
                    headers={"authorization": f"Bearer {self.api_key}"},
                )
            except httpx.HTTPError as exc:
                raise LLMError("OpenAI request failed before response") from exc

        if response.status_code >= 400:
            raise LLMError(f"OpenAI request failed with HTTP {response.status_code}")

        data = response.json()
        text = _extract_openai_output_text(data)
        cleaned = text.strip()
        if not cleaned:
            raise LLMError("OpenAI response was empty")
        return cleaned


def build_llm_client(*, provider: str, api_key: str, model: str, base_url: str | None = None, max_output_tokens: int = 1000) -> LLMClient:
    normalized = provider.lower().strip()
    if normalized == "gemini":
        return GeminiClient(api_key=api_key, model=model, max_output_tokens=max_output_tokens)
    if normalized in {"openai", "openai_responses"}:
        return OpenAIResponsesClient(api_key=api_key, model=model, base_url=base_url, max_output_tokens=max_output_tokens)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def _extract_openai_output_text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str):
        return direct
    output = data.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    raise LLMError("OpenAI response did not contain text")
