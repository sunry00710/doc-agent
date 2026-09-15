"""版本对比引擎。

三种引擎，结果里如实回报用的是哪一种（``ComparisonOutcome.engine``）：

- ``llm``：真实模型（self provider）做语义对比，识别「改写但语义等价」的段落；
- ``heuristic``：离线演示（``FakeProvider``）——段落级 diff + 文本相似度判定，本地启发式，
  不冒称模型能力；
- ``difflib``：真实模型不可用或返回非法结果时回退逐行 diff，``degraded=True``，
  前端必须显示降级提示。

模型只负责产出 category / summary / 原文片段；版本 ID 一律由后端绑定，避免模型张冠李戴。
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.providers.base import (
    CompletionRequest,
    ModelMessage,
    ModelProvider,
    ProviderError,
)
from app.quality.prompts import SYSTEM_PROMPT
from app.quality.schemas import ComparisonChange, ComparisonResult

COMPARISON_TYPE_LABELS: dict[str, str] = {
    "semantic": "语义",
    "requirements": "要求",
    "version": "版本",
    "precedent": "先例",
    "standards": "标准",
}

COMPARISON_FOCUS: dict[str, str] = {
    "semantic": (
        "识别两个版本之间意思变了没有、怎么变的：改写但语义等价的句子、口径或结论发生变化的句子、"
        "金额与数据变化、结构调整、语气与措辞强度变化。"
    ),
    "requirements": "对照写作要求与约定条款，指出新版是否满足这些要求，并给出原文证据。",
    "version": "给出两个不可变版本之间的完整差异，覆盖新增、删除、修改，并说明对事实与结论的影响。",
    "precedent": "把当前版本与已批准的先例对比，指出偏离先例之处。",
    "standards": "对照适用的标准与模板，指出不符合之处。",
}

CHANGE_CATEGORIES: frozenset[str] = frozenset(
    {
        "addition",
        "deletion",
        "modification",
        "semantic_rewrite",
        "data_change",
        "structure_change",
        "tone_change",
        "comment_response",
        "unchanged",
    }
)

MAX_CHANGES = 200
MAX_HEURISTIC_CHANGES = 40
MAX_RUN_UNITS = 60
_REWRITE_SIMILARITY = 0.35
_MIN_UNITS_FOR_REWRITE_CHECK = 3
MAX_FRAGMENT_CHARS = 2_000
MAX_SUMMARY_CHARS = 600
MAX_IMPACT_CHARS = 600
MAX_USER_MESSAGE_CHARS = 30_000
LLM_MAX_TOKENS = 2_048
LLM_TIMEOUT_SECONDS = 45.0
_HEURISTIC_EQUIVALENCE = 0.55

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_SENTENCE_END = re.compile(r"(?<=[。！？；])")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")


@dataclass(frozen=True)
class ComparisonOutcome:
    result: ComparisonResult
    engine: str
    degraded: bool = False
    degraded_reason: str | None = None
    truncated: bool = False


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…（已截断）"


def _label(comparison_type: str) -> str:
    return COMPARISON_TYPE_LABELS.get(comparison_type, comparison_type)


def _unchanged(version_a_id: str, version_b_id: str, summary: str) -> ComparisonResult:
    return ComparisonResult(
        changes=[
            ComparisonChange(
                category="unchanged",
                summary="两个版本内容一致",
                version_a_id=version_a_id,
                version_b_id=version_b_id,
            )
        ],
        summary=summary,
    )


# --- 引擎 1：逐行 diff（回退与基线） -------------------------------------------


def line_diff(source_a: str, source_b: str, version_a_id: str, version_b_id: str) -> ComparisonResult:
    lines_a, lines_b = source_a.splitlines(), source_b.splitlines()
    changes: list[ComparisonChange] = []
    matcher = difflib.SequenceMatcher(a=lines_a, b=lines_b)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old = "\n".join(lines_a[i1:i2])
        new = "\n".join(lines_b[j1:j2])
        category = {"insert": "addition", "delete": "deletion", "replace": "modification"}[tag]
        summary = (
            f"删除：{old}"
            if tag == "delete"
            else f"新增：{new}"
            if tag == "insert"
            else f"由“{old}”修改为“{new}”"
        )
        changes.append(
            ComparisonChange(
                category=category,
                summary=summary,
                old_text=_clip(old, MAX_FRAGMENT_CHARS),
                new_text=_clip(new, MAX_FRAGMENT_CHARS),
                version_a_id=version_a_id,
                version_b_id=version_b_id,
            )
        )
    if not changes:
        return _unchanged(version_a_id, version_b_id, "逐行差异对比完成，两个版本内容一致")
    return ComparisonResult(
        changes=changes, summary=f"逐行差异对比完成，共发现 {len(changes)} 项变化"
    )


# --- 引擎 2：离线启发式（FakeProvider 演示用） ---------------------------------


def _blocks(source: str) -> list[str]:
    """切到句子级：段落级 diff 会把整段判成一类变化，长审计段落可读性很差。"""
    units: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADING.match(stripped) or len(stripped) <= 40:
            units.append(stripped)
            continue
        units.extend(piece.strip() for piece in _SENTENCE_END.split(stripped) if piece.strip())
    return units


def _shape(text: str) -> str:
    return "heading" if _HEADING.match(text) else "body"


def _is_wholesale_rewrite(old_units: list[str], new_units: list[str]) -> bool:
    """连续多句都被替换且逐句相似度很低时，逐句配对会把无关句子硬凑成"由 A 改为 B"。"""
    if len(old_units) > MAX_RUN_UNITS or len(new_units) > MAX_RUN_UNITS:
        return True
    if len(old_units) < _MIN_UNITS_FOR_REWRITE_CHECK or len(new_units) < _MIN_UNITS_FOR_REWRITE_CHECK:
        return False
    ratios = [
        difflib.SequenceMatcher(a=old, b=new).ratio()
        for old, new in zip(old_units, new_units, strict=False)
    ]
    return sum(ratios) / len(ratios) < _REWRITE_SIMILARITY


def _classify(old: str, new: str) -> tuple[str, bool | None, str, str]:
    """返回 (category, semantic_equivalent, summary, impact)。"""
    if not old:
        return "addition", None, f"新增：{_clip(new, 120)}", "新增内容，需确认是否有依据支撑"
    if not new:
        return "deletion", None, f"删除：{_clip(old, 120)}", "删除内容，需确认是否影响结论与依据"
    if _NUMBER.findall(old) != _NUMBER.findall(new):
        return (
            "data_change",
            False,
            f"数据变化：由“{_clip(old, 100)}”改为“{_clip(new, 100)}”",
            "金额、比例或日期发生变化，需人工核对来源",
        )
    if _shape(old) != _shape(new):
        return (
            "structure_change",
            False,
            f"结构调整：“{_clip(old, 100)}”改为“{_clip(new, 100)}”",
            "层级或结构变化，需确认编号与引用同步更新",
        )
    ratio = difflib.SequenceMatcher(a=old, b=new).ratio()
    if ratio >= _HEURISTIC_EQUIVALENCE:
        return (
            "semantic_rewrite",
            True,
            f"语义等价改写：“{_clip(old, 100)}”→“{_clip(new, 100)}”",
            "意思未变，属于表述调整",
        )
    return (
        "modification",
        False,
        f"由“{_clip(old, 100)}”修改为“{_clip(new, 100)}”",
        "实质修改，需确认事实与结论是否同步调整",
    )


def heuristic_compare(
    source_a: str, source_b: str, _comparison_type: str, version_a_id: str, version_b_id: str
) -> ComparisonResult:
    blocks_a, blocks_b = _blocks(source_a), _blocks(source_b)
    matcher = difflib.SequenceMatcher(a=blocks_a, b=blocks_b, autojunk=False)
    changes: list[ComparisonChange] = []
    total = 0

    def emit(
        old: str,
        new: str,
        *,
        category: str | None = None,
        summary: str | None = None,
        impact: str | None = None,
        equivalent: bool | None = None,
    ) -> bool:
        if len(changes) >= MAX_HEURISTIC_CHANGES:
            return False
        if category is None:
            category, equivalent, summary, impact = _classify(old, new)
        changes.append(
            ComparisonChange(
                category=category,
                summary=summary,
                old_text=_clip(old, MAX_FRAGMENT_CHARS),
                new_text=_clip(new, MAX_FRAGMENT_CHARS),
                impact=impact,
                semantic_equivalent=equivalent,
                version_a_id=version_a_id,
                version_b_id=version_b_id,
            )
        )
        return True

    def emit_run(old_units: list[str], new_units: list[str]) -> None:
        if not old_units:
            category, summary, impact = "addition", f"整段新增：约 {len(new_units)} 句", "新增整段内容，需确认依据是否充分"
        elif not new_units:
            category, summary, impact = "deletion", f"整段删除：约 {len(old_units)} 句", "删除整段内容，需确认是否影响结论与依据"
        else:
            category = "modification"
            summary = f"整段重写：旧版 {len(old_units)} 句 → 新版 {len(new_units)} 句"
            impact = "整段替换，逐句对齐不可靠，建议人工核对"
        emit(
            "\n".join(old_units),
            "\n".join(new_units),
            category=category,
            summary=summary,
            impact=impact,
        )

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_units, new_units = blocks_a[i1:i2], blocks_b[j1:j2]
        total += max(len(old_units), len(new_units))
        if _is_wholesale_rewrite(old_units, new_units):
            # 整段替换：如实标注"整段重写"，不把两个不同文书的句子硬凑成"由 A 改为 B"
            emit_run(old_units, new_units)
        else:
            for index in range(max(len(old_units), len(new_units))):
                old = old_units[index] if index < len(old_units) else ""
                new = new_units[index] if index < len(new_units) else ""
                emit(old, new)
    if not changes:
        return _unchanged(version_a_id, version_b_id, "离线启发式对比完成，两个版本内容一致")
    summary = f"离线启发式对比完成，共发现 {len(changes)} 处变化"
    if total > len(changes):
        summary += f"（变化较多，仅逐条列出前 {len(changes)} 处，共约 {total} 处）"
    return ComparisonResult(changes=changes, summary=summary)


# --- 引擎 3：真实模型语义对比 --------------------------------------------------


def _instructions(comparison_type: str) -> str:
    focus = COMPARISON_FOCUS.get(comparison_type, COMPARISON_FOCUS["version"])
    return (
        f"请对比下面两个不可变版本，对比重点：{focus}\n"
        "只输出一个 JSON 对象，不要输出解释文字或 Markdown 代码块，结构如下：\n"
        '{"changes": [{"category": "semantic_rewrite", "summary": "…", "old_text": "…", '
        '"new_text": "…", "impact": "…", "semantic_equivalent": true}]}\n'
        "category 只能取：addition、deletion、modification、semantic_rewrite、data_change、"
        "structure_change、tone_change、comment_response、unchanged。\n"
        "summary 用一句中文说明改了什么，不超过 200 字；old_text、new_text 必须是原文里真实出现的片段，"
        "不得改写；impact 说明对事实、依据或结论的影响；semantic_equivalent 表示改动前后意思是否等价。\n"
        "不要编造正文中没有的内容；两侧完全一致时返回 {\"changes\": []}。"
    )


def build_comparison_messages(
    source_a: str, source_b: str, comparison_type: str
) -> tuple[list[ModelMessage], bool]:
    header = _instructions(comparison_type)
    per_side = max(1_000, (MAX_USER_MESSAGE_CHARS - len(header) - 200) // 2)
    truncated = len(source_a) > per_side or len(source_b) > per_side
    user = (
        f"{header}\n\n【版本 A 正文】\n{_clip(source_a, per_side)}"
        f"\n\n【版本 B 正文】\n{_clip(source_b, per_side)}"
    )
    return [
        ModelMessage(role="system", content=SYSTEM_PROMPT),
        ModelMessage(role="user", content=user),
    ], truncated


def _extract_json_object(content: str) -> dict[str, Any]:
    text = _FENCE.sub("", content.strip()).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start == -1:
            raise ValueError("model response contained no JSON object") from None
        try:
            payload, _end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            raise ValueError("model response contained invalid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("model response was not a JSON object")
    return payload


def parse_llm_changes(content: str, version_a_id: str, version_b_id: str) -> list[ComparisonChange]:
    payload = _extract_json_object(content)
    raw = payload.get("changes")
    if raw is None:
        raise ValueError("model response did not contain a changes list")
    if not isinstance(raw, list):
        raise TypeError("model changes must be a list")
    if not raw:
        return [
            ComparisonChange(
                category="unchanged",
                summary="两个版本内容一致",
                version_a_id=version_a_id,
                version_b_id=version_b_id,
            )
        ]
    changes: list[ComparisonChange] = []
    for item in raw[:MAX_CHANGES]:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        category = str(item.get("category") or "").strip()
        equivalent = item.get("semantic_equivalent")
        changes.append(
            ComparisonChange(
                category=category if category in CHANGE_CATEGORIES else "modification",
                summary=_clip(summary, MAX_SUMMARY_CHARS),
                old_text=_clip(str(item.get("old_text") or ""), MAX_FRAGMENT_CHARS),
                new_text=_clip(str(item.get("new_text") or ""), MAX_FRAGMENT_CHARS),
                impact=_clip(str(item.get("impact") or ""), MAX_IMPACT_CHARS),
                semantic_equivalent=equivalent if isinstance(equivalent, bool) else None,
                version_a_id=version_a_id,
                version_b_id=version_b_id,
            )
        )
    if not changes:
        raise ValueError("model response contained no usable changes")
    return changes


def _llm_compare(
    provider: ModelProvider,
    source_a: str,
    source_b: str,
    comparison_type: str,
    version_a_id: str,
    version_b_id: str,
    *,
    max_tokens: int,
    timeout_seconds: float,
) -> tuple[ComparisonResult, bool]:
    messages, truncated = build_comparison_messages(source_a, source_b, comparison_type)
    completion = provider.complete(
        CompletionRequest(
            messages=messages, max_tokens=max_tokens, timeout_seconds=timeout_seconds
        )
    )
    content = (completion.content or "").strip()
    if not content:
        raise ProviderError("provider_invalid_response")
    changes = parse_llm_changes(content, version_a_id, version_b_id)
    result = ComparisonResult(
        changes=changes,
        summary=f"{_label(comparison_type)}对比完成（模型语义分析），共发现 {len(changes)} 项变化",
    )
    return result, truncated


def compare_sources(
    source_a: str,
    source_b: str,
    comparison_type: str,
    version_a_id: str,
    version_b_id: str,
    provider: ModelProvider | None,
    *,
    max_tokens: int = LLM_MAX_TOKENS,
    timeout_seconds: float = LLM_TIMEOUT_SECONDS,
) -> ComparisonOutcome:
    """按「真实模型 → 离线启发式 → 逐行 diff」的顺序取第一个可用引擎。"""
    if provider is None:
        return ComparisonOutcome(
            result=line_diff(source_a, source_b, version_a_id, version_b_id),
            engine="difflib",
            degraded=True,
            degraded_reason="provider_not_configured",
        )
    if getattr(provider, "offline", False):
        return ComparisonOutcome(
            result=heuristic_compare(
                source_a, source_b, comparison_type, version_a_id, version_b_id
            ),
            engine="heuristic",
        )
    try:
        result, truncated = _llm_compare(
            provider,
            source_a,
            source_b,
            comparison_type,
            version_a_id,
            version_b_id,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        return ComparisonOutcome(result=result, engine="llm", truncated=truncated)
    except ProviderError as exc:
        reason = exc.code
    except (ValueError, TypeError):
        reason = "provider_invalid_response"
    return ComparisonOutcome(
        result=line_diff(source_a, source_b, version_a_id, version_b_id),
        engine="difflib",
        degraded=True,
        degraded_reason=reason,
    )
