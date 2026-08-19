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


@dataclass(frozen=True)
class AgentContext:
    project_id: UUID | None = None
    document_version_id: UUID | None = None
    knowledge_space_ids: tuple[UUID, ...] = ()
    permissions: frozenset[str] = frozenset()
    confirmed: bool = False
    idempotency_key: str | None = None


class ToolTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    name: str
    arguments: str = ""
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


class AgentRunner:
    def __init__(self, provider: ModelProvider, tools: ToolRegistry, limits: AgentLimits | None = None) -> None:
        self.provider = provider
        self.tools = tools
        self.limits = limits or AgentLimits()

    def run(self, user: User, text: str, context: AgentContext) -> AgentResult:
        del user  # Actor-bound authorization is assembled by the router before this loop starts.
        messages = [ModelMessage(role="user", content=text)]
        traces: list[ToolTrace] = []
        input_tokens = output_tokens = 0
        started = time.monotonic()
        for _round in range(self.limits.max_rounds):
            if len(messages) >= self.limits.max_messages or time.monotonic() - started > self.limits.max_duration_seconds:
                return AgentResult(traces=traces, stop_reason="budget_exhausted", input_tokens=input_tokens, output_tokens=output_tokens)
            try:
                completion = self.provider.complete(
                    CompletionRequest(messages=messages, tools=[tool.schema() for tool in self.tools.definitions()])
                )
            except ProviderError as exc:
                return AgentResult(traces=traces, stop_reason=exc.code, input_tokens=input_tokens, output_tokens=output_tokens)
            input_tokens += completion.input_tokens
            output_tokens += completion.output_tokens
            if input_tokens + output_tokens > self.limits.max_tokens:
                return AgentResult(traces=traces, stop_reason="budget_exhausted", input_tokens=input_tokens, output_tokens=output_tokens)
            messages.append(ModelMessage(role="assistant", content=completion.content))
            if not completion.tool_calls:
                return AgentResult(text=completion.content or "", traces=traces, input_tokens=input_tokens, output_tokens=output_tokens)
            for call in completion.tool_calls:
                trace = ToolTrace(tool_call_id=call.id, name=call.name, arguments=call.arguments, status="pending")
                result, error_code = self.tools.execute(call.name, call.arguments, context)
                if error_code:
                    trace.status = "denied" if error_code == "permission_denied" else "failed"
                    trace.error_code = error_code
                    safe_result = {"error": error_code}
                else:
                    trace.status = "succeeded"
                    trace.result = result
                    safe_result = result
                traces.append(trace)
                messages.append(
                    ModelMessage(
                        role="tool", tool_call_id=call.id, name=call.name, content=json.dumps(safe_result, default=str)
                    )
                )
        return AgentResult(traces=traces, stop_reason="max_rounds", input_tokens=input_tokens, output_tokens=output_tokens)
