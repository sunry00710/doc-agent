from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[BaseModel, Any], object]
    mutating: bool = False
    permission: str | None = None

    def schema(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def definitions(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def execute(self, name: str, arguments: str, context: Any) -> tuple[object | None, str | None]:
        definition = self._tools.get(name)
        if definition is None:
            return None, "validation_error"
        if definition.permission and definition.permission not in context.permissions:
            return None, "permission_denied"
        if definition.mutating and (not context.confirmed or not context.idempotency_key):
            return None, "permission_denied"
        try:
            parsed = json.loads(arguments)
            if not isinstance(parsed, dict):
                return None, "validation_error"
            model = definition.input_model.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            return None, "validation_error"
        try:
            return definition.handler(model, context), None
        except Exception:  # noqa: BLE001 - tool failures are intentionally converted to safe errors.
            return None, "internal_error"
