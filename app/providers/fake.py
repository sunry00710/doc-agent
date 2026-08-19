from collections import deque
from collections.abc import Iterable

from app.agent.messages import AssistantMessage
from app.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ProviderError,
)


class FakeProvider(ModelProvider):
    """Deterministic offline provider that records every completion request."""

    def __init__(self, responses: Iterable[AssistantMessage | CompletionResult | Exception] = ()) -> None:
        self.responses = deque(responses)
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if not self.responses:
            raise ProviderError("provider_unavailable", retryable=False)
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        if isinstance(response, CompletionResult):
            return response
        return CompletionResult(
            content=response.content,
            tool_calls=[call.to_provider() for call in response.tool_calls],
        )
