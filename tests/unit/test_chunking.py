from itertools import pairwise

from app.knowledge.chunking import MAX_CHUNK_SIZE, chunk_markdown


def test_chinese_markdown_chunks_are_stable_bounded_and_exact():
    source = "# 总则\r\n\r\n第一段包含中文标点，内容必须保持稳定。\r\n\r\n## 范围\r\n\r\n" + "第二段。" * 200

    first = chunk_markdown(source, version_id="version-a")
    second = chunk_markdown(source, version_id="version-a")

    assert [(chunk.id, chunk.heading_path, chunk.start_offset, chunk.end_offset) for chunk in first] == [
        (chunk.id, chunk.heading_path, chunk.start_offset, chunk.end_offset) for chunk in second
    ]
    normalized = source.replace("\r\n", "\n")
    assert all(chunk.end_offset - chunk.start_offset <= MAX_CHUNK_SIZE for chunk in first)
    assert all(normalized[chunk.start_offset : chunk.end_offset] == chunk.text for chunk in first)
    assert all(left.end_offset <= right.start_offset for left, right in pairwise(first))
    assert first[0].heading_path == ("总则",)
    assert all(chunk.heading_path == ("总则", "范围") for chunk in first[1:])
    assert len({chunk.id for chunk in first}) == len(first)
    assert {chunk.id for chunk in first}.isdisjoint({chunk.id for chunk in chunk_markdown(source, version_id="version-b")})


def test_chunking_groups_chinese_markdown_paragraphs_and_excludes_headings():
    source = "# 总则\n\n第一段。\n仍是第一段。\n\n## 范围\n\n第二段。\n\n### 细则\n\n第三段。"

    chunks = chunk_markdown(source, version_id="version-a", max_chunk_size=100)

    assert [chunk.text for chunk in chunks] == ["第一段。\n仍是第一段。", "第二段。", "第三段。"]
    assert [chunk.heading_path for chunk in chunks] == [("总则",), ("总则", "范围"), ("总则", "范围", "细则")]
    assert all("总则" not in chunk.text and "范围" not in chunk.text and "细则" not in chunk.text for chunk in chunks)
    assert all(source[chunk.start_offset : chunk.end_offset] == chunk.text for chunk in chunks)


def test_chunking_handles_empty_and_skipped_heading_levels_and_text_identity():
    source = "#\n\n前言。\n\n### 三级\n\n内容。\n\n# 新章\n\n尾声。"

    chunks = chunk_markdown(source, version_id="v", max_chunk_size=2)

    assert [chunk.heading_path for chunk in chunks] == [(), (), ("三级",), ("三级",), ("新章",), ("新章",)]
    assert [chunk.text for chunk in chunks] == ["前言", "。", "内容", "。", "尾声", "。"]
    changed = chunk_markdown(source.replace("内容", "内涵"), version_id="v", max_chunk_size=2)
    assert chunks[2].id != changed[2].id
    assert all(chunk.end_offset - chunk.start_offset <= 2 for chunk in chunks)
