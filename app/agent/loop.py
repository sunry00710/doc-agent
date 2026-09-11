from __future__ import annotations

import json
import time
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agent.tools import ToolRegistry
from app.identity.models import User
from app.providers.base import (
    CompletionRequest,
    ModelMessage,
    ModelProvider,
    ProviderError,
)


@dataclass(frozen=True)
class AgentLimits:
    max_rounds: int = 4
    max_messages: int = 16
    max_duration_seconds: float = 20.0
    max_tokens: int = 8_192
    max_cost_micro_units: int = 0


@dataclass(frozen=True)
class AgentContext:
    project_id: UUID | None = None
    document_version_id: UUID | None = None
    knowledge_space_ids: tuple[UUID, ...] = ()
    permissions: frozenset[str] = frozenset()
    confirmed: bool = False
    idempotency_key: str | None = None
    actor_id: str | None = None
    request_id: str | None = None
    deadline: float | None = None
    session: object | None = None
    actor: User | None = None
    storage: object | None = None


class ToolTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    name: str
    arguments: object = Field(default_factory=dict)
    status: str
    result: object | None = None
    error_code: str | None = None


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    traces: list[ToolTrace] = Field(default_factory=list)
    stop_reason: str = "completed"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micro_units: int = 0
    request_id: str | None = None
    provider_request_id: str | None = None


class AgentRunner:
    def __init__(
        self,
        provider: ModelProvider,
        tools: ToolRegistry,
        limits: AgentLimits | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.limits = limits or AgentLimits()
        self.system_prompt = system_prompt

    def run(self, user: User, text: str, context: AgentContext) -> AgentResult:
        if context.actor_id is None:
            context = AgentContext(**{**context.__dict__, "actor_id": str(user.id)})
        started = time.monotonic()
        deadline = context.deadline if context.deadline is not None else started + self.limits.max_duration_seconds
        messages: list[ModelMessage] = []
        if self.system_prompt:
            messages.append(ModelMessage(role="system", content=self.system_prompt))
        messages.append(ModelMessage(role="user", content=text))
        traces: list[ToolTrace] = []
        input_tokens = output_tokens = cost_micro_units = 0
        provider_request_id: str | None = None

        def stopped() -> bool:
            return time.monotonic() >= deadline

        def result(reason: str, *, answer: str = "") -> AgentResult:
            return AgentResult(text=answer, traces=traces, stop_reason=reason, input_tokens=input_tokens, output_tokens=output_tokens, cost_micro_units=cost_micro_units, request_id=context.request_id, provider_request_id=provider_request_id)

        for _round in range(self.limits.max_rounds):
            remaining_tokens = self.limits.max_tokens - input_tokens - output_tokens
            if (
                self._conversation_length(messages) >= self.limits.max_messages
                or remaining_tokens <= 0
                or stopped()
            ):
                return result("budget_exhausted")
            try:
                completion = self.provider.complete(CompletionRequest(
                    messages=messages,
                    tools=[tool.schema() for tool in self.tools.definitions()],
                    max_tokens=remaining_tokens,
                    request_id=context.request_id,
                    timeout_seconds=max(0.001, deadline - time.monotonic()),
                ))
            except ProviderError as exc:
                return result(exc.code)
            if stopped():
                return result("budget_exhausted")
            input_tokens += completion.input_tokens
            output_tokens += completion.output_tokens
            cost_micro_units += completion.cost_micro_units
            provider_request_id = completion.request_id
            if input_tokens + output_tokens > self.limits.max_tokens or (self.limits.max_cost_micro_units and cost_micro_units > self.limits.max_cost_micro_units):
                return result("budget_exhausted")
            messages.append(ModelMessage(role="assistant", content=completion.content, tool_calls=completion.tool_calls))
            if not completion.tool_calls:
                return result("completed", answer=completion.content or "")
            for call in completion.tool_calls:
                if self._conversation_length(messages) >= self.limits.max_messages or stopped():
                    return result("budget_exhausted")
                raw_result, error_code, definition, parsed = self.tools.execute_detailed(call.name, call.arguments, context)
                trace = ToolTrace(tool_call_id=call.id, name=call.name, arguments=self.tools.trace_arguments(definition, parsed), status="pending")
                if stopped():
                    return result("budget_exhausted")
                if error_code:
                    trace.status = "denied" if error_code == "permission_denied" else "failed"
                    trace.error_code = error_code
                    safe_result: object = {"error": error_code}
                else:
                    trace.status = "succeeded"
                    safe_result = self.tools.safe_output(definition, parsed, raw_result)
                    trace.result = self.tools.trace_result(definition, parsed, raw_result)
                traces.append(trace)
                messages.append(ModelMessage(role="tool", tool_call_id=call.id, name=call.name, content=json.dumps(safe_result)))
                if stopped():
                    return result("budget_exhausted")
        return result("max_rounds")

    @staticmethod
    def _conversation_length(messages: list[ModelMessage]) -> int:
        """system 提示词是固定开销，不占用 max_messages 代表的对话轮次预算。"""
        return sum(1 for message in messages if message.role != "system")
