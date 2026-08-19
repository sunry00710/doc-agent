from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProviderToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    arguments: str = Field(max_length=16_000)


class ModelMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = Field(default=None, max_length=32_000)
    tool_call_id: str | None = Field(default=None, max_length=128)
    name: str | None = Field(default=None, max_length=128)
    tool_calls: list[ProviderToolCall] = Field(default_factory=list, max_length=32)


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ModelMessage] = Field(min_length=1, max_length=32)
    tools: list[dict[str, object]] = Field(default_factory=list, max_length=32)
    model: str | None = Field(default=None, max_length=256)
    max_tokens: int = Field(default=1_024, ge=1, le=16_384)
    request_id: str | None = Field(default=None, max_length=128)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)


class CompletionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, max_length=32_000)
    tool_calls: list[ProviderToolCall] = Field(default_factory=list, max_length=32)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_micro_units: int = Field(default=0, ge=0)
    request_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_content_or_tool_calls(self) -> CompletionResult:
        if not (self.content and self.content.strip()) and not self.tool_calls:
            raise ValueError("completion must contain content or tool calls")
        return self


class ProviderError(Exception):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class ModelProvider(ABC):
    @abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Produce one model completion."""
