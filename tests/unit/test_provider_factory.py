from __future__ import annotations

import pytest

from app.core.config import Settings
from app.providers.base import ProviderError
from app.providers.factory import build_provider
from app.providers.fake import FakeProvider
from app.providers.openai_compatible import OpenAICompatibleProvider


def test_default_provider_is_fake() -> None:
    assert isinstance(build_provider(Settings(environment="test")), FakeProvider)


def test_self_provider_requires_configuration() -> None:
    with pytest.raises(ProviderError, match="self_ai_not_configured"):
        build_provider(Settings(environment="test", model_provider="self"))


def test_self_provider_builds_openai_compatible() -> None:
    settings = Settings(
        environment="test",
        model_provider="self",
        self_ai_endpoint="https://api.deepseek.com/v1",
        self_ai_api_key="sk-test",
        self_ai_model="deepseek-chat",
    )
    provider = build_provider(settings)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.endpoint == "https://api.deepseek.com/v1"
    assert provider.model == "deepseek-chat"


def test_internal_provider_requires_configuration() -> None:
    with pytest.raises(ProviderError, match="internal_api_not_configured"):
        build_provider(Settings(environment="test", model_provider="internal"))


def test_internal_provider_builds_openai_compatible() -> None:
    settings = Settings(
        environment="test",
        model_provider="internal",
        internal_api_endpoint="https://gw.corp.internal/v1",
        internal_api_key="corp-key",
        internal_api_model="corp-model",
    )
    provider = build_provider(settings)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.endpoint == "https://gw.corp.internal/v1"
    assert provider.model == "corp-model"


def test_self_and_internal_are_independent() -> None:
    """两个接口各自独立：配置了 self 不影响 internal 的未配置报错。"""
    settings = Settings(
        environment="test",
        model_provider="internal",
        self_ai_endpoint="https://api.deepseek.com/v1",
        self_ai_api_key="sk-test",
        self_ai_model="deepseek-chat",
    )
    with pytest.raises(ProviderError, match="internal_api_not_configured"):
        build_provider(settings)
