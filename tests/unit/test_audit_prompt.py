from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel

from app.agent.loop import AgentContext, AgentLimits, AgentRunner
from app.agent.messages import AssistantMessage, ToolCall
from app.agent.tools import ToolDefinition, ToolRegistry
from app.identity.models import Role, User
from app.providers.fake import FakeProvider
from app.quality.prompts import (
    CAPABILITY_PROMPTS,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_system_prompt,
)


class EchoArgs(BaseModel):
    value: str


class EchoOutput(BaseModel):
    value: str


def actor() -> User:
    return User(id=str(uuid4()), username="audit-user", password_hash="hash", role=Role.user)


def echo_registry(calls: list[str]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "echo",
            "Echo",
            EchoArgs,
            lambda args, _context: calls.append(args.value) or {"value": args.value},
            output_model=EchoOutput,
        )
    )
    return registry


def test_system_prompt_is_sent_as_the_first_message():
    provider = FakeProvider([AssistantMessage(content="ok")])

    result = AgentRunner(provider, ToolRegistry(), system_prompt="审计文书规范").run(
        actor(), "这份报告有什么问题？", AgentContext()
    )

    assert result.text == "ok"
    messages = provider.requests[0].messages
    assert [message.role for message in messages] == ["system", "user"]
    assert messages[0].content == "审计文书规范"
    assert messages[-1].content == "这份报告有什么问题？"


def test_runner_without_system_prompt_keeps_the_original_message_shape():
    provider = FakeProvider([AssistantMessage(content="ok")])

    AgentRunner(provider, ToolRegistry()).run(actor(), "问题", AgentContext())

    assert [message.role for message in provider.requests[0].messages] == ["user"]


def test_system_prompt_does_not_consume_the_message_budget():
    calls: list[str] = []
    provider = FakeProvider(
        [
            AssistantMessage(tool_calls=[ToolCall(id="one", name="echo", arguments='{"value":"one"}')]),
            AssistantMessage(content="done"),
        ]
    )

    result = AgentRunner(
        provider,
        echo_registry(calls),
        AgentLimits(max_messages=3),
        system_prompt=SYSTEM_PROMPT,
    ).run(actor(), "go", AgentContext())

    # system 是固定开销：max_messages=3 时仍然执行了一次工具调用
    assert calls == ["one"]
    assert len(result.traces) == 1
    assert provider.requests[0].messages[0].role == "system"


def test_system_prompt_is_composed_of_every_capability_prompt():
    # 反向守住 Q7 的病根：prompts.py 里的常量必须真的被注入，不能是死代码
    for name, prompt in CAPABILITY_PROMPTS.items():
        assert prompt in SYSTEM_PROMPT, name
    assert SYSTEM_PROMPT == build_system_prompt()
    assert PROMPT_VERSION in SYSTEM_PROMPT
    assert len(SYSTEM_PROMPT) < 32_000  # ModelMessage.content 上限


def test_system_prompt_states_the_tool_contracts_the_backend_enforces():
    assert "evidence" in SYSTEM_PROMPT
    assert "精确切片" in SYSTEM_PROMPT
    assert "human_review_required" in SYSTEM_PROMPT
    assert "logical_mismatch" in SYSTEM_PROMPT
    assert "version_a_id" in SYSTEM_PROMPT and "version_b_id" in SYSTEM_PROMPT
    assert "coverage" in SYSTEM_PROMPT
