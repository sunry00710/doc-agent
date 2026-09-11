from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.errors import AppError

Authorizer = Callable[[Any, BaseModel], bool]
_TRACE_OUTPUT_MAX_CHARS = 8_192
_MISSING = object()


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[BaseModel, Any], object]
    mutating: bool = False
    permission: str | None = None
    authorizer: Authorizer | None = None
    output_model: type[BaseModel] | None = None
    trace_serializer: Callable[[BaseModel, object], object] | None = None
    trace_output_model: type[BaseModel] | None = None

    def schema(self) -> dict[str, object]:
        return {"name": self.name, "description": self.description, "parameters": self.input_model.model_json_schema()}


@dataclass
class _IdempotencyEntry:
    expires_at: float
    result: object
    event: threading.Event
    owner: threading.Thread | None


class InMemoryIdempotencyStore:
    """Process-local bounded claims and completed results for mutating tool calls."""

    def __init__(
        self, *, max_entries: int = 1_024, ttl_seconds: float = 300, wait_timeout_seconds: float = 1.0
    ) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.wait_timeout_seconds = wait_timeout_seconds
        self._entries: OrderedDict[tuple[str, str, str], _IdempotencyEntry] = OrderedDict()
        self._lock = threading.Lock()

    def _cleanup(self, now: float) -> None:
        for key, entry in list(self._entries.items()):
            if entry.expires_at > now:
                continue
            if entry.result is not _MISSING or entry.event.is_set() or not self._owner_alive(entry):
                self._entries.pop(key, None)
        while len(self._entries) > self.max_entries:
            key, entry = next(iter(self._entries.items()))
            if entry.result is _MISSING and not entry.event.is_set() and self._owner_alive(entry):
                break
            self._entries.pop(key)

    @staticmethod
    def _owner_alive(entry: _IdempotencyEntry) -> bool:
        return entry.owner is not None and entry.owner.is_alive()

    def claim(self, key: tuple[str, str, str]) -> tuple[str, object | None, threading.Event | None]:
        with self._lock:
            now = time.monotonic()
            self._cleanup(now)
            entry = self._entries.get(key)
            if entry is None:
                if len(self._entries) >= self.max_entries:
                    return "unavailable", None, None
                event = threading.Event()
                self._entries[key] = _IdempotencyEntry(now + self.ttl_seconds, _MISSING, event, threading.current_thread())
                return "owner", None, event
            self._entries.move_to_end(key)
            if entry.result is not _MISSING:
                return "cached", entry.result, None
            # Never steal an expired in-flight claim: its handler may still be
            # producing an irreversible side effect. Followers receive the
            # bounded wait/in-progress response instead.
            return "follower", None, entry.event

    def complete(self, key: tuple[str, str, str], result: object, event: threading.Event) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.event is event:
                self._entries[key] = _IdempotencyEntry(time.monotonic() + self.ttl_seconds, result, event, None)
                self._entries.move_to_end(key)
                self._cleanup(time.monotonic())
            event.set()

    def release(self, key: tuple[str, str, str], event: threading.Event) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.event is event:
                self._entries.pop(key, None)
            event.set()

    def wait(self, key: tuple[str, str, str], event: threading.Event) -> tuple[object | None, str | None]:
        if not event.wait(self.wait_timeout_seconds):
            return None, "idempotency_in_progress"
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.result is not _MISSING:
                self._entries.move_to_end(key)
                return entry.result, None
        return None, "idempotency_in_progress"


class ToolRegistry:
    def __init__(self, idempotency_store: InMemoryIdempotencyStore | None = None) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self.idempotency_store = idempotency_store or InMemoryIdempotencyStore()

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool already registered: {definition.name}")
        if definition.mutating and not (definition.permission or definition.authorizer):
            raise ValueError("mutating tools require an explicit permission or authorizer")
        if definition.trace_serializer and definition.trace_output_model is None:
            raise ValueError("trace serializers require a trace output model")
        if definition.trace_output_model is not None and definition.trace_output_model.model_config.get("extra") != "forbid":
            raise ValueError("trace output models must forbid extra fields")
        self._tools[definition.name] = definition

    def definitions(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def execute_detailed(self, name: str, arguments: str, context: Any) -> tuple[object | None, str | None, ToolDefinition | None, BaseModel | None]:
        definition = self._tools.get(name)
        if definition is None:
            return None, "validation_error", None, None
        try:
            parsed = json.loads(arguments)
            if not isinstance(parsed, dict):
                return None, "validation_error", definition, None
            model = definition.input_model.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            return None, "validation_error", definition, None
        if definition.permission and definition.permission not in context.permissions:
            return None, "permission_denied", definition, model
        if definition.authorizer and not definition.authorizer(context, model):
            return None, "permission_denied", definition, model
        if definition.mutating:
            if not context.confirmed or not context.idempotency_key or not context.actor_id:
                return None, "permission_denied", definition, model
            key = (context.actor_id, definition.name, context.idempotency_key)
            claim, cached, event = self.idempotency_store.claim(key)
            if claim == "cached":
                return cached, None, definition, model
            if claim == "follower":
                result, error = self.idempotency_store.wait(key, event)
                return result, error, definition, model
            if claim == "unavailable":
                return None, "idempotency_in_progress", definition, model
        try:
            result = definition.handler(model, context)
        except AppError as exc:
            if definition.mutating:
                self.idempotency_store.release(key, event)
            return None, exc.code, definition, model
        except Exception:  # noqa: BLE001
            if definition.mutating:
                self.idempotency_store.release(key, event)
            return None, "internal_error", definition, model
        if definition.mutating:
            self.idempotency_store.complete(key, result, event)
        return result, None, definition, model

    def execute(self, name: str, arguments: str, context: Any) -> tuple[object | None, str | None]:
        result, error_code, _definition, _model = self.execute_detailed(name, arguments, context)
        return result, error_code

    @staticmethod
    def safe_output(definition: ToolDefinition | None, model: BaseModel | None, result: object) -> object:
        if definition is None or model is None:
            return {"status": "completed"}
        if definition.output_model is not None:
            try:
                return definition.output_model.model_validate(result).model_dump(mode="json")
            except ValidationError:
                return {"error": "internal_error"}
        return {"status": "completed"}

    @staticmethod
    def trace_arguments(definition: ToolDefinition | None, model: BaseModel | None) -> object:
        if definition is None or model is None:
            return {"fields": []}
        return {"fields": sorted(model.model_fields_set)}

    @staticmethod
    def trace_result(definition: ToolDefinition | None, model: BaseModel | None, result: object) -> object:
        if (
            definition
            and definition.trace_serializer
            and definition.trace_output_model
            and definition.trace_output_model.model_config.get("extra") == "forbid"
            and model
        ):
            try:
                serialized = definition.trace_serializer(model, result)
                output = definition.trace_output_model.model_validate(serialized).model_dump(mode="json")
                if len(json.dumps(output, separators=(",", ":"), ensure_ascii=False)) <= _TRACE_OUTPUT_MAX_CHARS:
                    return output
            except Exception:  # noqa: BLE001,S110 - trace generation must never expose or fail a tool call.
                pass
        return ToolRegistry.safe_output(definition, model, result)
