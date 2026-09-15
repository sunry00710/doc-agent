from __future__ import annotations

import pytest
from pydantic import ValidationError

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


def test_unknown_provider_is_rejected_at_settings_load() -> None:
    """provider 取值由 Settings 的 Literal 约束，非法值在构造配置时就报错。"""
    with pytest.raises(ValidationError):
        Settings(environment="test", model_provider="openai")
