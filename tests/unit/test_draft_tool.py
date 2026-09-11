"""Agent 起草能力：draft_document 工具与离线演示链路。

边界：工具只产出草稿文本，不写入任何文档；落库由用户在界面上确认后走
「保存为新版本」。这让「起草」与「只建议不改稿」的既有边界保持一致。
"""
from __future__ import annotations

import json

from app.agent.tools import ToolRegistry
from app.providers.base import CompletionRequest, ModelMessage
from app.providers.fake import FakeProvider
from app.quality.prompts import CAPABILITY_PROMPTS, PROMPT_VERSION, SYSTEM_PROMPT
from app.quality.tools import DraftOutput, register_quality_tools


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_quality_tools(registry)
    return registry


def test_draft_tool_is_registered_as_non_mutating():
    registry = make_registry()
    definition = next(item for item in registry.definitions() if item.name == "draft_document")
    assert definition.mutating is False
    assert definition.permission is None
    assert definition.output_model is DraftOutput


def test_draft_tool_returns_text_without_touching_storage():
    registry = make_registry()
    arguments = json.dumps(
        {"title": "整改情况报告", "content": "一、基本情况。" * 12, "notes": "依据用户提供材料"},
        ensure_ascii=False,
    )
    result, error = registry.execute("draft_document", arguments, context=object())
    assert error is None
    assert isinstance(result, DraftOutput)
    assert result.title == "整改情况报告"
    assert result.content.startswith("一、基本情况。")
    assert result.notes == "依据用户提供材料"


def test_draft_tool_rejects_short_or_malformed_input():
    registry = make_registry()
    too_short, error = registry.execute(
        "draft_document", json.dumps({"title": "报告", "content": "太短"}), context=object()
    )
    assert too_short is None
    assert error == "validation_error"


def test_offline_provider_triggers_draft_flow_for_draft_intent():
    provider = FakeProvider()
    completion = provider.complete(
        CompletionRequest(
            messages=[ModelMessage(role="user", content="请起草一份《采购整改情况报告》")],
            tools=[{"name": "draft_document"}],
        )
    )
    assert completion.tool_calls
    call = completion.tool_calls[0]
    assert call.name == "draft_document"
    arguments = json.loads(call.arguments)
    assert arguments["title"] == "采购整改情况报告"


def test_system_prompt_declares_draft_capability():
    assert "draft_document" in CAPABILITY_PROMPTS
    assert "draft_document" in SYSTEM_PROMPT
    assert "不得声称“已创建文档”" in SYSTEM_PROMPT
    assert PROMPT_VERSION == "quality-v3"
