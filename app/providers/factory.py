from __future__ import annotations

from app.core.config import Settings
from app.providers.base import ModelProvider, ProviderError
from app.providers.fake import FakeProvider
from app.providers.openai_compatible import OpenAICompatibleProvider


def build_provider(settings: Settings) -> ModelProvider:
    choice = settings.model_provider.lower()
    if choice == "fake":
        return FakeProvider()
    if choice == "self":
        return _build_self_ai(settings)
    raise ProviderError(f"unknown_provider:{choice}")


def _build_self_ai(settings: Settings) -> ModelProvider:
    if not settings.self_ai_endpoint or not settings.self_ai_model:
        raise ProviderError(
            "self_ai_not_configured: 请设置 SELF_AI_ENDPOINT / SELF_AI_API_KEY / SELF_AI_MODEL"
        )
    return OpenAICompatibleProvider(
        endpoint=settings.self_ai_endpoint,
        api_key=settings.self_ai_api_key.get_secret_value(),
        model=settings.self_ai_model,
        timeout_seconds=settings.provider_timeout_seconds,
    )
