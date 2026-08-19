from __future__ import annotations

import threading
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from app.agent.loop import AgentContext, AgentLimits, AgentRunner
from app.agent.messages import AssistantMessage, ToolCall
from app.agent.tools import InMemoryIdempotencyStore, ToolDefinition, ToolRegistry
from app.identity.models import Role, User
from app.providers.base import CompletionResult, ProviderToolCall
from app.providers.fake import FakeProvider


class EchoArgs(__import__("pydantic").BaseModel):
    value: str
    project_id: str | None = None


class SafeOutput(__import__("pydantic").BaseModel):
    value: str


def actor() -> User:
    return User(id=str(uuid4()), username="agent-user", password_hash="hash", role=Role.user)


def test_follow_up_history_includes_assistant_tool_calls():
    provider = FakeProvider([
        AssistantMessage(tool_calls=[ToolCall(id="call-1", name="echo", arguments='{"value":"hello"}')]),
        AssistantMessage(content="done"),
    ])
    tools = ToolRegistry()
    tools.register(ToolDefinition("echo", "Echo", EchoArgs, lambda args, _: {"value": args.value}, output_model=SafeOutput))

    assert AgentRunner(provider, tools).run(actor(), "go", AgentContext()).text == "done"
    assistant = provider.requests[1].messages[-2]
    assert assistant.role == "assistant"
    assert assistant.tool_calls == [ProviderToolCall(id="call-1", name="echo", arguments='{"value":"hello"}')]


def test_empty_completion_is_invalid_for_fake_provider():
    provider = FakeProvider([AssistantMessage()])
    result = AgentRunner(provider, ToolRegistry()).run(actor(), "go", AgentContext())
    assert result.stop_reason == "provider_invalid_response"


def test_remaining_token_budget_caps_request_and_rejects_over_budget_result():
    provider = FakeProvider([CompletionResult(content="too much", input_tokens=3, output_tokens=4)])
    result = AgentRunner(provider, ToolRegistry(), AgentLimits(max_tokens=5)).run(actor(), "go", AgentContext())
    assert provider.requests[0].max_tokens == 5
    assert result.stop_reason == "budget_exhausted"
    assert result.text == ""


def test_message_capacity_stops_tools_before_extra_execution():
    calls: list[str] = []
    provider = FakeProvider([AssistantMessage(tool_calls=[
        ToolCall(id="one", name="echo", arguments='{"value":"one"}'),
        ToolCall(id="two", name="echo", arguments='{"value":"two"}'),
    ])])
    tools = ToolRegistry()
    tools.register(ToolDefinition("echo", "Echo", EchoArgs, lambda args, _: calls.append(args.value) or {"value": args.value}, output_model=SafeOutput))
    result = AgentRunner(provider, tools, AgentLimits(max_messages=3)).run(actor(), "go", AgentContext())
    assert calls == ["one"]
    assert result.stop_reason == "budget_exhausted"
    assert len(result.traces) == 1


def test_late_provider_result_and_late_tool_stop_without_follow_up(monkeypatch):
    ticks = iter([0.0, 0.0, 0.0, 2.0, 2.0])
    monkeypatch.setattr("app.agent.loop.time.monotonic", lambda: next(ticks))
    provider = FakeProvider([AssistantMessage(content="late")])
    assert AgentRunner(provider, ToolRegistry(), AgentLimits(max_duration_seconds=1)).run(actor(), "go", AgentContext()).stop_reason == "budget_exhausted"

    calls: list[str] = []
    provider = FakeProvider([AssistantMessage(tool_calls=[ToolCall(id="x", name="echo", arguments='{"value":"x"}')])])
    tools = ToolRegistry()
    tools.register(ToolDefinition("echo", "Echo", EchoArgs, lambda args, _: calls.append(args.value) or {"value": args.value}, output_model=SafeOutput))
    monkeypatch.setattr("app.agent.loop.time.monotonic", lambda: 2.0)
    result = AgentRunner(provider, tools, AgentLimits(max_duration_seconds=1)).run(actor(), "go", AgentContext(deadline=1.0))
    assert result.stop_reason == "budget_exhausted"
    assert calls == []


def test_cost_budget_and_usage_are_enforced():
    provider = FakeProvider([CompletionResult(content="costly", cost_micro_units=8)])
    result = AgentRunner(provider, ToolRegistry(), AgentLimits(max_cost_micro_units=5)).run(actor(), "go", AgentContext())
    assert result.stop_reason == "budget_exhausted"
    assert result.cost_micro_units == 8


def test_authorizer_denies_unrelated_resource_and_mutating_tool_needs_policy():
    provider = FakeProvider([AssistantMessage(tool_calls=[ToolCall(id="x", name="read", arguments='{"value":"x","project_id":"other"}')]), AssistantMessage(content="done")])
    tools = ToolRegistry()
    tools.register(ToolDefinition("read", "Read", EchoArgs, lambda args, _: {"value": args.value}, output_model=SafeOutput, authorizer=lambda ctx, args: args.project_id == str(ctx.project_id)))
    result = AgentRunner(provider, tools).run(actor(), "go", AgentContext(project_id=uuid4()))
    assert result.traces[0].status == "denied"
    with pytest.raises(ValueError, match="mutating"):
        tools.register(ToolDefinition("bad", "Bad", EchoArgs, lambda *_: None, mutating=True))


def test_idempotency_deduplicates_only_successes_per_actor_and_tool():
    calls: list[str] = []
    registry = ToolRegistry(InMemoryIdempotencyStore(max_entries=4, ttl_seconds=60))
    registry.register(ToolDefinition("write", "Write", EchoArgs, lambda args, _: calls.append(args.value) or {"value": args.value}, mutating=True, permission="write", output_model=SafeOutput))
    context = AgentContext(actor_id="a", permissions=frozenset({"write"}), confirmed=True, idempotency_key="same")
    assert registry.execute("write", '{"value":"one"}', context)[1] is None
    assert registry.execute("write", '{"value":"two"}', context)[1] is None
    assert calls == ["one"]
    assert registry.execute("write", '{"value":"three"}', AgentContext(actor_id="b", permissions=frozenset({"write"}), confirmed=True, idempotency_key="same"))[1] is None
    assert calls == ["one", "three"]


def test_trace_and_model_result_are_redacted_without_output_model():
    secret = "secret-argument-and-result"
    provider = FakeProvider([AssistantMessage(tool_calls=[ToolCall(id="x", name="unsafe", arguments='{"value":"secret-argument-and-result"}')]), AssistantMessage(content="done")])
    tools = ToolRegistry()
    tools.register(ToolDefinition("unsafe", "Unsafe", EchoArgs, lambda args, _: {"secret": args.value}))
    result = AgentRunner(provider, tools).run(actor(), "go", AgentContext())
    rendered = result.model_dump_json()
    assert secret not in rendered
    assert secret not in provider.requests[1].messages[-1].content
    assert result.traces[0].arguments == {"fields": ["value"]}


class StrictTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_value: str


class PermissiveTrace(BaseModel):
    public_value: str


def test_idempotency_expired_inflight_claim_is_not_stolen(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("app.agent.tools.time.monotonic", lambda: now[0])
    store = InMemoryIdempotencyStore(ttl_seconds=1)
    key = ("actor", "write", "key")
    assert store.claim(key)[0] == "owner"
    now[0] = 2.0
    assert store.claim(key)[0] == "follower"


def test_trace_serializer_requires_strict_output_model():
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="forbid"):
        registry.register(ToolDefinition(
            "unsafe", "Unsafe", EchoArgs, lambda *_: None,
            trace_serializer=lambda *_: {"public_value": "ok"}, trace_output_model=PermissiveTrace,
        ))


def test_mutating_concurrent_identical_calls_execute_once_and_followers_receive_result():
    entered = threading.Event()
    release = threading.Event()
    barrier = threading.Barrier(2)
    calls = 0
    calls_lock = threading.Lock()
    registry = ToolRegistry(InMemoryIdempotencyStore(ttl_seconds=60, wait_timeout_seconds=1))

    def handler(args: EchoArgs, _: AgentContext) -> dict[str, str]:
        nonlocal calls
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(1)
        return {"value": args.value}

    registry.register(ToolDefinition("write", "Write", EchoArgs, handler, mutating=True, permission="write"))
    context = AgentContext(actor_id="actor", permissions=frozenset({"write"}), confirmed=True, idempotency_key="key")
    outcomes: list[tuple[object | None, str | None]] = []

    def invoke() -> None:
        barrier.wait()
        outcomes.append(registry.execute("write", '{"value":"one"}', context))

    threads = [threading.Thread(target=invoke) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert entered.wait(1)
    release.set()
    for thread in threads:
        thread.join(1)
        assert not thread.is_alive()
    assert calls == 1
    assert outcomes == [({"value": "one"}, None), ({"value": "one"}, None)]


def test_mutating_failure_releases_claim_for_retry():
    calls = 0
    registry = ToolRegistry(InMemoryIdempotencyStore(ttl_seconds=60))

    def handler(_: EchoArgs, __: AgentContext) -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        return {"value": "retried"}

    registry.register(ToolDefinition("write", "Write", EchoArgs, handler, mutating=True, permission="write"))
    context = AgentContext(actor_id="actor", permissions=frozenset({"write"}), confirmed=True, idempotency_key="key")
    assert registry.execute("write", '{"value":"one"}', context) == (None, "internal_error")
    assert registry.execute("write", '{"value":"one"}', context) == ({"value": "retried"}, None)
    assert calls == 2


def test_trace_serializer_requires_strict_model_and_redacts_malicious_or_oversized_output():
    secret = "private-trace-secret"
    registry = ToolRegistry()
    malicious = ToolDefinition(
        "unsafe", "Unsafe", EchoArgs, lambda args, _: {"secret": args.value},
        trace_serializer=lambda _args, result: {"public_value": "ok", "secret": result["secret"]},
        trace_output_model=StrictTrace,
    )
    oversized = ToolDefinition(
        "large", "Large", EchoArgs, lambda _args, _: None,
        trace_serializer=lambda *_: {"public_value": "x" * 20_000}, trace_output_model=StrictTrace,
    )
    model = EchoArgs(value=secret)
    assert registry.trace_result(malicious, model, {"secret": secret}) == {"status": "completed"}
    assert registry.trace_result(oversized, model, None) == {"status": "completed"}


def test_trace_serializer_validated_strict_output_is_exposed():
    definition = ToolDefinition(
        "safe", "Safe", EchoArgs, lambda _args, _: {"value": "internal"},
        trace_serializer=lambda _args, _result: {"public_value": "safe"}, trace_output_model=StrictTrace,
    )
    assert ToolRegistry.trace_result(definition, EchoArgs(value="secret"), {"value": "secret"}) == {"public_value": "safe"}
