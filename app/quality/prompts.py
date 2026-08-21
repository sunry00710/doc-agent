from __future__ import annotations

PROMPT_VERSION = "quality-v1"
CHECK_PROMPT = "审查不可变文档，返回 JSON findings、summary 与 coverage。每个 finding 的 evidence 必须是原文精确切片。"
REWRITE_PROMPT = "只提出带原文证据的改写建议，不修改原文。"
COMPARE_PROMPT = "比较版本 A 与 B，所有变更必须同时绑定两个版本 ID。"
REVIEW_PROMPT = "解释批注意图并提出基于原文的建议；不确定时说明待确认项。"
JUDGE_PROMPT = "输出结构化质量发现；逻辑或结论性风险必须标记为需人工复核。"
