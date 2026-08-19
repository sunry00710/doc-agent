from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel

from app.agent.loop import AgentContext, AgentLimits, AgentRunner
from app.agent.messages import AssistantMessage, ToolCall
from app.agent.tools import ToolDefinition, ToolRegistry
from app.identity.models import Role, User
from app.providers.fake import FakeProvider


class EchoArgs(BaseModel):
    value: str


def actor() -> User:
    return User(id=str(uuid4()), username="agent-user", password_hash="hash", role=Role.user)


def test_runner_returns_final_text_response():
    provider = FakeProvider([AssistantMessage(content="A concise answer")])

    result = AgentRunner(provider, ToolRegistry()).run(actor(), "Question", AgentContext())

    assert result.text == "A concise answer"
    assert result.traces == []
    assert provider.requests[0].messages[-1].content == "Question"


def test_runner_executes_tool_and_returns_follow_up_answer():
    provider = FakeProvider(
        [
            AssistantMessage(tool_calls=[ToolCall(id="call-1", name="echo", arguments='{"value":"hello"}')]),
            AssistantMessage(content="Tool completed"),
        ]
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition("echo", "Echo a value", EchoArgs, lambda args, _context: {"echo": args.value})
    )

    result = AgentRunner(provider, registry).run(actor(), "Use the tool", AgentContext())

    assert result.text == "Tool completed"
    assert result.traces[0].status == "succeeded"
    assert result.traces[0].result == {"status": "completed"}
    assert provider.requests[1].messages[-1].role == "tool"


def test_runner_handles_multiple_and_invalid_tool_calls_safely():
    provider = FakeProvider(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall(id="good", name="echo", arguments='{"value":"ok"}'),
                    ToolCall(id="bad", name="echo", arguments="not json"),
                    ToolCall(id="unknown", name="missing", arguments="{}"),
                ]
            ),
            AssistantMessage(content="Recovered"),
        ]
    )
    registry = ToolRegistry()
    registry.register(ToolDefinition("echo", "Echo", EchoArgs, lambda args, _context: args.model_dump()))

    result = AgentRunner(provider, registry).run(actor(), "Run tools", AgentContext())

    assert result.text == "Recovered"
    assert [trace.status for trace in result.traces] == ["succeeded", "failed", "failed"]
    assert [trace.error_code for trace in result.traces[1:]] == ["validation_error", "validation_error"]


def test_runner_enforces_tool_permission_and_confirmation():
    provider = FakeProvider(
        [
            AssistantMessage(tool_calls=[ToolCall(id="deny", name="write", arguments='{"value":"x"}')]),
            AssistantMessage(content="Cannot write"),
        ]
    )
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "write",
            "Mutating tool",
            EchoArgs,
            lambda args, _context: args.model_dump(),
            mutating=True,
            permission="document:write",
        )
    )

    result = AgentRunner(provider, registry).run(actor(), "Write", AgentContext())

    assert result.traces[0].status == "denied"
    assert result.traces[0].error_code == "permission_denied"


def test_runner_enforces_max_rounds_and_initializes_trace_arguments():
    provider = FakeProvider(
        [AssistantMessage(tool_calls=[ToolCall(id="loop", name="echo", arguments='{"value":"x"}')])]
        * 3
    )
    registry = ToolRegistry()
    registry.register(ToolDefinition("echo", "Echo", EchoArgs, lambda args, _context: args.model_dump()))

    result = AgentRunner(provider, registry, AgentLimits(max_rounds=2)).run(
        actor(), "Loop", AgentContext()
    )

    assert result.stop_reason == "max_rounds"
    assert len(result.traces) == 2
    assert result.traces[0].arguments == {"fields": ["value"]}
