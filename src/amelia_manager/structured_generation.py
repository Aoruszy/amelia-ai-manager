from __future__ import annotations

import inspect
from typing import Any


async def generate_with_optional_schema(
    llm,
    prompt: str,
    *,
    response_schema: dict[str, Any],
) -> str:
    """Request provider-level JSON schema when the LLM adapter supports it.

    Test fakes and legacy adapters often expose generate(prompt) only. Keep them
    working while production GeminiClient receives responseMimeType/responseSchema.
    """
    generate = llm.generate
    signature = inspect.signature(generate)
    parameters = signature.parameters
    supports_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
    supports_schema = "response_schema" in parameters and "response_mime_type" in parameters
    if supports_kwargs or supports_schema:
        return await generate(
            prompt,
            response_mime_type="application/json",
            response_schema=response_schema,
        )
    return await generate(prompt)
