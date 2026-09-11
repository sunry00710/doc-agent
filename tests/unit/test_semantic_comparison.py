from __future__ import annotations

import json

import pytest

from app.providers.base import (
    CompletionRequest,
    CompletionResult,
    ModelProvider,
    ProviderError,
)
from app.providers.fake import FakeProvider
from app.quality.comparison import (
    build_comparison_messages,
    compare_sources,
    heuristic_compare,
    line_diff,
    parse_llm_changes,
)

VERSION_A = "11111111-1111-1111-1111-111111111111"
VERSION_B = "22222222-2222-2222-2222-222222222222"

SOURCE_A = "审计发现：某单位未按规定归档采购合同，涉及金额 30 万元。\n\n上述问题需限期整改。"
SOURCE_B = "审计发现：某单位未按规定妥善归档采购合同，涉及金额 45 万元。\n\n上述问题需限期整改。"


class StubProvider(ModelProvider):
    """真实模型的测试替身：返回脚本化内容或抛错。"""

    def __init__(self, *, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.content is not None
        return CompletionResult(content=self.content)


def _payload(changes: list[dict]) -> str:
    return json.dumps({"changes": changes}, ensure_ascii=False)


# --- 引擎选择 -----------------------------------------------------------------


def test_llm_engine_is_used_for_a_scripted_model():
    provider = StubProvider(
        content=_payload(
            [
                {
                    "category": "semantic_rewrite",
                    "summary": "补语调整，归档要求表述更完整",
                    "old_text": "未按规定归档采购合同",
                    "new_text": "未按规定妥善归档采购合同",
                    "impact": "意思未变",
                    "semantic_equivalent": True,
                },
                {
                    "category": "data_change",
                    "summary": "金额由 30 万元改为 45 万元",
                    "old_text": "30 万元",
                    "new_text": "45 万元",
                    "impact": "金额变化需核对取证记录",
                    "semantic_equivalent": False,
                },
            ]
        )
    )

    outcome = compare_sources(SOURCE_A, SOURCE_B, "semantic", VERSION_A, VERSION_B, provider)

    assert outcome.engine == "llm"
    assert outcome.degraded is False
    assert [change.category for change in outcome.result.changes] == [
        "semantic_rewrite",
        "data_change",
    ]
    assert outcome.result.changes[0].semantic_equivalent is True
    assert outcome.result.changes[0].version_a_id == VERSION_A
    assert outcome.result.changes[0].version_b_id == VERSION_B
    assert "语义" in outcome.result.summary


def test_offline_provider_uses_the_local_heuristic_instead_of_faking_a_model():
    outcome = compare_sources(SOURCE_A, SOURCE_B, "semantic", VERSION_A, VERSION_B, FakeProvider())

    assert outcome.engine == "heuristic"
    assert outcome.degraded is False
    categories = {change.category for change in outcome.result.changes}
    assert "data_change" in categories
    assert all(change.version_a_id == VERSION_A for change in outcome.result.changes)


def test_missing_provider_degrades_to_line_diff():
    outcome = compare_sources(SOURCE_A, SOURCE_B, "semantic", VERSION_A, VERSION_B, None)

    assert outcome.engine == "difflib"
    assert outcome.degraded is True
    assert outcome.degraded_reason == "provider_not_configured"
    assert outcome.result.changes


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ProviderError("provider_unavailable", retryable=True), "provider_unavailable"),
        (ProviderError("provider_invalid_response"), "provider_invalid_response"),
    ],
)
def test_provider_failure_degrades_to_line_diff_with_reason(error, reason):
    outcome = compare_sources(
        SOURCE_A, SOURCE_B, "semantic", VERSION_A, VERSION_B, StubProvider(error=error)
    )

    assert outcome.engine == "difflib"
    assert outcome.degraded is True
    assert outcome.degraded_reason == reason


def test_unparsable_model_output_degrades_instead_of_raising():
    provider = StubProvider(content="抱歉，我无法完成这个对比。")

    outcome = compare_sources(SOURCE_A, SOURCE_B, "semantic", VERSION_A, VERSION_B, provider)

    assert outcome.engine == "difflib"
    assert outcome.degraded_reason == "provider_invalid_response"


# --- 模型输出解析 --------------------------------------------------------------


def test_parse_llm_changes_accepts_fenced_json_and_binds_versions():
    content = "```json\n" + _payload(
        [{"category": "tone_change", "summary": "措辞趋于缓和", "semantic_equivalent": False}]
    ) + "\n```"

    changes = parse_llm_changes(content, VERSION_A, VERSION_B)

    assert changes[0].category == "tone_change"
    assert changes[0].version_a_id == VERSION_A
    assert changes[0].version_b_id == VERSION_B


def test_parse_llm_changes_clamps_unknown_category_and_skips_empty_summaries():
    content = _payload(
        [
            {"category": "hallucinated", "summary": "有摘要"},
            {"category": "addition", "summary": "   "},
        ]
    )

    changes = parse_llm_changes(content, VERSION_A, VERSION_B)

    assert [change.category for change in changes] == ["modification"]


def test_parse_llm_changes_maps_identical_versions_to_unchanged():
    changes = parse_llm_changes(_payload([]), VERSION_A, VERSION_B)

    assert changes[0].category == "unchanged"


@pytest.mark.parametrize(
    "content", ["no json here", '{"summary": "缺少 changes"}', '{"changes": "oops"}']
)
def test_parse_llm_changes_rejects_unusable_payloads(content: str):
    with pytest.raises((ValueError, TypeError)):
        parse_llm_changes(content, VERSION_A, VERSION_B)


# --- 其它 ---------------------------------------------------------------------


def test_line_diff_reports_unchanged_for_identical_sources():
    result = line_diff(SOURCE_A, SOURCE_A, VERSION_A, VERSION_B)

    assert len(result.changes) == 1
    assert result.changes[0].category == "unchanged"


def test_heuristic_compare_flags_semantic_equivalence():
    source_b = SOURCE_A.replace("未按规定归档", "未按规定及时归档")

    result = heuristic_compare(SOURCE_A, source_b, "semantic", VERSION_A, VERSION_B)

    assert len(result.changes) == 1
    assert result.changes[0].category == "semantic_rewrite"
    assert result.changes[0].semantic_equivalent is True


def test_comparison_messages_stay_within_the_model_message_limit():
    messages, truncated = build_comparison_messages("甲" * 60_000, "乙" * 60_000, "semantic")

    assert truncated is True
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert len(messages[1].content or "") < 32_000
    assert "版本 A 正文" in (messages[1].content or "")
