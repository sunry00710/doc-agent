"""版本对比结果的绑定校验。

注意命名：本模块只做「变更是否绑定到请求中的两个版本」的校验；
真正的对比算法（LLM/启发式/difflib 三引擎）在 ``app/quality/comparison.py``。
"""
from __future__ import annotations

from app.quality.schemas import ComparisonResult


def compare_documents(result: ComparisonResult, version_a_id: str, version_b_id: str) -> ComparisonResult:
    for change in result.changes:
        if change.version_a_id != version_a_id or change.version_b_id != version_b_id:
            raise ValueError("comparison change is not bound to requested versions")
    return result
