from __future__ import annotations

import time
from collections.abc import Callable
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
        input_cost_micro_units_per_token: int = 0,
        output_cost_micro_units_per_token: int = 0,
        client: httpx.Client | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.input_cost_micro_units_per_token = input_cost_micro_units_per_token
        self.output_cost_micro_units_per_token = output_cost_micro_units_per_token
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._monotonic = monotonic
        self._sleeper = sleeper

    def complete(self, request: CompletionRequest) -> CompletionResult:
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": [self._message_payload(message.model_dump(exclude_none=True)) for message in request.messages],
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in request.tools]
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if request.request_id:
            headers["X-Request-ID"] = request.request_id
        timeout = min(self.timeout_seconds, request.timeout_seconds) if request.timeout_seconds else self.timeout_seconds
        deadline = self._monotonic() + timeout
        for attempt in range(self.retries + 1):
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise ProviderError("provider_unavailable", retryable=True)
            try:
                response = self.client.post(
                    f"{self.endpoint}/chat/completions", json=payload, headers=headers, timeout=remaining
                )
                if response.status_code in {429} or response.status_code >= 500:
                    if attempt < self.retries:
                        self._sleep_for_retry(0.05 * (attempt + 1), deadline)
                        continue
                    raise ProviderError("provider_unavailable", retryable=True)
                if response.status_code >= 400:
                    raise ProviderError("provider_invalid_response")
                return self._parse_response(response.json(), response.headers.get("X-Request-ID"))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt < self.retries:
                    self._sleep_for_retry(0.05 * (attempt + 1), deadline)
                    continue
                raise ProviderError("provider_unavailable", retryable=True) from exc
            except ProviderError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError("provider_invalid_response") from exc
        raise ProviderError("provider_unavailable", retryable=True)

    def _sleep_for_retry(self, backoff: float, deadline: float) -> None:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise ProviderError("provider_unavailable", retryable=True)
        self._sleeper(min(backoff, remaining))

    @staticmethod
    def _message_payload(message: dict[str, Any]) -> dict[str, Any]:
        tool_calls = message.pop("tool_calls", [])
        if tool_calls:
            message["tool_calls"] = [
                {"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": call["arguments"]}}
                for call in tool_calls
            ]
        return message

    def _parse_response(self, payload: dict[str, Any], request_id: str | None) -> CompletionResult:
        choice = payload["choices"][0]["message"]
        usage = payload.get("usage", {})
        tool_calls = [
            ProviderToolCall(id=call["id"], name=call["function"]["name"], arguments=call["function"].get("arguments", "{}"))
            for call in choice.get("tool_calls", [])
        ]
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        return CompletionResult(
            content=choice.get("content"), tool_calls=tool_calls, input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micro_units=(input_tokens * self.input_cost_micro_units_per_token + output_tokens * self.output_cost_micro_units_per_token),
            request_id=request_id,
        )
