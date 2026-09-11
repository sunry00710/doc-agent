from __future__ import annotations

from app.core.config import Settings
from app.providers.base import ModelProvider, ProviderError
from app.providers.fake import FakeProvider
from app.providers.openai_compatible import OpenAICompatibleProvider

# 集团内网 API 的具体协议尚未确定。接入前假设其为 OpenAI 兼容协议，
# 拿到接口文档后：若非兼容，新增独立 Provider 类并在 build_provider 中改接。
_INTERNAL_API_PROTOCOL_NOTE = (
    "集团内网 API 尚未配置。请在 .env 中设置 INTERNAL_API_ENDPOINT / "
    "INTERNAL_API_KEY / INTERNAL_API_MODEL 后再使用 MODEL_PROVIDER=internal。"
)


def build_provider(settings: Settings) -> ModelProvider:
    choice = settings.model_provider.lower()
    if choice == "fake":
        return FakeProvider()
    if choice == "self":
        return _build_self_ai(settings)
    if choice == "internal":
        return _build_internal_api(settings)
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


def _build_internal_api(settings: Settings) -> ModelProvider:
    if not settings.internal_api_endpoint or not settings.internal_api_model:
        raise ProviderError(f"internal_api_not_configured: {_INTERNAL_API_PROTOCOL_NOTE}")
    return OpenAICompatibleProvider(
        endpoint=settings.internal_api_endpoint,
        api_key=settings.internal_api_key.get_secret_value(),
        model=settings.internal_api_model,
        timeout_seconds=settings.provider_timeout_seconds,
    )
