from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.providers.base import ModelMessage, ProviderToolCall


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    arguments: str = Field(max_length=16_000)

    def to_provider(self) -> ProviderToolCall:
        return ProviderToolCall(id=self.id, name=self.name, arguments=self.arguments)


class AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, max_length=32_000)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=32)

    def to_model_message(self) -> ModelMessage:
        return ModelMessage(
            role="assistant", content=self.content, tool_calls=[call.to_provider() for call in self.tool_calls]
        )
