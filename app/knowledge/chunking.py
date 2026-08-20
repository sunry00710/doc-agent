from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_CHUNK_SIZE = 1_000
_HEADING = re.compile(r"^(#{1,6})(?:[ \t]+(.*?)[ \t]*)?$")


@dataclass(frozen=True)
class Chunk:
    id: str
    heading_path: tuple[str, ...]
    start_offset: int
    end_offset: int
    text: str


def _chunk_id(version_id: str, start: int, end: int, text: str) -> str:
    """Bind the stable identity to the source version, range, and exact text."""
    identity = f"{version_id}\0{start}\0{end}\0{text}".encode()
    return hashlib.sha256(identity).hexdigest()


def chunk_markdown(source: str, version_id: str, max_chunk_size: int = MAX_CHUNK_SIZE) -> list[Chunk]:
    """Split normalized Markdown paragraphs without placing headings in chunks."""
    if max_chunk_size < 1:
        raise ValueError("max_chunk_size must be positive")
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    headings: list[str] = []
    chunks: list[Chunk] = []
    paragraph_start: int | None = None
    paragraph_end = 0

    def flush_paragraph() -> None:
        nonlocal paragraph_start
        if paragraph_start is None:
            return
        for start in range(paragraph_start, paragraph_end, max_chunk_size):
            end = min(start + max_chunk_size, paragraph_end)
            chunk_text = source[start:end]
            chunks.append(Chunk(_chunk_id(version_id, start, end, chunk_text), tuple(headings), start, end, chunk_text))
        paragraph_start = None

    cursor = 0
    for line in source.splitlines(keepends=True):
        line_start = cursor
        cursor += len(line)
        content = line.rstrip("\n")
        heading = _HEADING.match(content)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            title = (heading.group(2) or "").strip()
            if title:
                headings = headings[: level - 1] + [title]
            continue
        if not content.strip():
            flush_paragraph()
            continue
        if paragraph_start is None:
            paragraph_start = line_start
        paragraph_end = line_start + len(content)
    flush_paragraph()
    return chunks
