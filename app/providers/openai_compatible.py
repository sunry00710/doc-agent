from __future__ import annotations

import time
from typing import Any

import httpx

from app.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ProviderError,
    ProviderToolCall,
)


class OpenAICompatibleProvider(ModelProvider):
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 30.0,
        retries: int = 1,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.client = client or httpx.Client(timeout=timeout_seconds)

    def complete(self, request: CompletionRequest) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": [message.model_dump(exclude_none=True) for message in request.messages],
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in request.tools]
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if request.request_id:
            headers["X-Request-ID"] = request.request_id
        for attempt in range(self.retries + 1):
            try:
                response = self.client.post(f"{self.endpoint}/chat/completions", json=payload, headers=headers)
                if response.status_code >= 500 and attempt < self.retries:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                response.raise_for_status()
                return self._parse_response(response.json(), response.headers.get("X-Request-ID"))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt < self.retries:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise ProviderError("provider_unavailable", retryable=True) from exc
            except httpx.HTTPStatusError as exc:
                raise ProviderError("provider_unavailable", retryable=exc.response.status_code >= 500) from exc
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError("provider_invalid_response") from exc
        raise ProviderError("provider_unavailable", retryable=True)

    @staticmethod
    def _parse_response(payload: dict[str, Any], request_id: str | None) -> CompletionResult:
        choice = payload["choices"][0]["message"]
        usage = payload.get("usage", {})
        tool_calls = [
            ProviderToolCall(
                id=call["id"],
                name=call["function"]["name"],
                arguments=call["function"].get("arguments", "{}"),
            )
            for call in choice.get("tool_calls", [])
        ]
        return CompletionResult(
            content=choice.get("content"),
            tool_calls=tool_calls,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            request_id=request_id,
        )
