from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelMessage,
    ProviderError,
)
from app.providers.openai_compatible import OpenAICompatibleProvider


def test_completion_result_rejects_empty_response():
    with pytest.raises(ValueError):
        CompletionResult()


def test_openai_second_request_serializes_assistant_tool_calls_and_request_id():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    provider = OpenAICompatibleProvider("https://provider.invalid", "secret", "model", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.complete(CompletionRequest(
        messages=[
            ModelMessage(role="user", content="go"),
            ModelMessage(role="assistant", tool_calls=[{"id": "c", "name": "echo", "arguments": "{}"}]),
            ModelMessage(role="tool", tool_call_id="c", name="echo", content="{}"),
        ],
        request_id="safe-request-id",
    ))
    body: dict[str, Any] = json.loads(captured[0].content)
    assert captured[0].headers["X-Request-ID"] == "safe-request-id"
    assert body["messages"][1]["tool_calls"][0]["function"]["name"] == "echo"
    assert result.content == "done"


@pytest.mark.parametrize("status, attempts", [(400, 1), (401, 1), (429, 2), (500, 2)])
def test_openai_retries_only_retryable_statuses(status: int, attempts: int):
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": {"private": "never expose"}})

    provider = OpenAICompatibleProvider("https://provider.invalid", "secret", "model", retries=1, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as caught:
        provider.complete(CompletionRequest(messages=[ModelMessage(role="user", content="go")]))
    assert calls == attempts
    assert caught.value.code == ("provider_unavailable" if status in {429, 500} else "provider_invalid_response")


def test_openai_empty_payload_becomes_safe_invalid_response():
    provider = OpenAICompatibleProvider("https://provider.invalid", "secret", "model", client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {}}]}))))
    with pytest.raises(ProviderError, match="provider_invalid_response"):
        provider.complete(CompletionRequest(messages=[ModelMessage(role="user", content="go")]))


def test_openai_uses_remaining_deadline_as_timeout():
    observed: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request.extensions["timeout"]["connect"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    # 剩余超时 = deadline - monotonic()。用真实时钟时该值会随平台时钟精度漂移：
    # Windows 粒度粗，两次调用常返回同一值 -> 恰好 2.5；Linux 纳秒级 -> 2.4999995。
    # 注入常量时钟，让断言与运行环境无关。
    provider = OpenAICompatibleProvider(
        "https://provider.invalid",
        "secret",
        "model",
        timeout_seconds=30,
        monotonic=lambda: 100.0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    provider.complete(CompletionRequest(messages=[ModelMessage(role="user", content="go")], timeout_seconds=2.5))
    assert observed == [2.5]


def test_openai_cost_uses_integer_micro_units():
    provider = OpenAICompatibleProvider("https://provider.invalid", "secret", "model", input_cost_micro_units_per_token=2, output_cost_micro_units_per_token=3, client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "done"}}], "usage": {"prompt_tokens": 4, "completion_tokens": 5}}))))
    assert provider.complete(CompletionRequest(messages=[ModelMessage(role="user", content="go")])).cost_micro_units == 23


def test_openai_stops_after_timeout_consumes_total_request_budget():
    calls = 0
    clock = iter([0.0, 0.0, 1.0])

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out")

    provider = OpenAICompatibleProvider(
        "https://provider.invalid", "secret", "model", retries=2,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        monotonic=lambda: next(clock), sleeper=lambda _: None,
    )
    with pytest.raises(ProviderError, match="provider_unavailable"):
        provider.complete(CompletionRequest(messages=[ModelMessage(role="user", content="go")], timeout_seconds=1))
    assert calls == 1


def test_openai_retries_when_total_request_budget_remains():
    observed_timeouts: list[float] = []
    sleeps: list[float] = []
    clock_values = iter([0.0, 0.0, 0.0, 0.1, 0.1])

    def handler(request: httpx.Request) -> httpx.Response:
        observed_timeouts.append(request.extensions["timeout"]["connect"])
        if len(observed_timeouts) == 1:
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    provider = OpenAICompatibleProvider(
        "https://provider.invalid", "secret", "model", retries=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        monotonic=lambda: next(clock_values), sleeper=sleeps.append,
    )
    assert provider.complete(CompletionRequest(messages=[ModelMessage(role="user", content="go")], timeout_seconds=1)).content == "done"
    assert observed_timeouts == [1.0, 0.9]
    assert sleeps == [0.05]
