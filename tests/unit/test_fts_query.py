from __future__ import annotations

from app.knowledge.search import _fts_query, _fts_query_any, _query_terms


def test_query_terms_split_chinese_into_characters():
    # 索引侧每个汉字单独成词，查询侧必须保持一致
    assert _query_terms("差旅补助") == ["差", "旅", "补", "助"]


def test_query_terms_keep_latin_and_digits_whole():
    assert _query_terms("RAG 2026 检索") == ["RAG", "2026", "检", "索"]


def test_and_query_requires_every_term():
    assert _fts_query("差旅补助") == '"差" AND "旅" AND "补" AND "助"'


def test_fallback_query_uses_adjacent_bigrams():
    # 索引里单字 token 保留原文顺序，相邻二字短语即真正的 bigram 匹配
    assert _fts_query_any("差旅补助标准") == '"差 旅" OR "旅 补" OR "补 助" OR "助 标" OR "标 准"'


def test_blank_query_produces_empty_expressions():
    assert _fts_query("   ") == ""
    assert _fts_query_any("   ") == ""


def test_fallback_is_empty_when_no_bigram_is_available():
    # 单字查询、纯拉丁查询都没有 bigram：兜底检索式为空，调用方据此跳过第二次查询
    assert _fts_query_any("印") == ""
    assert _fts_query_any("shared-indexed-deleted") == ""
