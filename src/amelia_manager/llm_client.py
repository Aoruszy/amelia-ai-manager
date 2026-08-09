from __future__ import annotations

import httpx
from typing import Any


class LLMError(RuntimeError):
    pass


class GeminiClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
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
                "maxOutputTokens": 350,
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
