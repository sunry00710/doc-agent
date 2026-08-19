from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings


@dataclass(frozen=True)
class StoredContent:
    storage_key: str
    content_sha256: str
    content: bytes


class FileStorage:
    def __init__(self, settings: Settings):
        self.root = settings.storage_dir.resolve()
        self.max_upload_bytes = settings.max_upload_bytes

    def store(self, filename: str | None, content: bytes) -> StoredContent:
        normalized = self._validate_and_normalize(filename, content)
        storage_key = f"documents/{uuid4()}/{uuid4()}.txt"
        path = self.path_for(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(normalized)
        return StoredContent(
            storage_key=storage_key,
            content_sha256=hashlib.sha256(normalized).hexdigest(),
            content=normalized,
        )

    def read(self, storage_key: str) -> bytes:
        return self.path_for(storage_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        path = self.path_for(storage_key)
        if path.exists():
            path.unlink()

    def path_for(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Invalid storage key") from exc
        return candidate

    def _validate_and_normalize(self, filename: str | None, content: bytes) -> bytes:
        suffix = Path(filename or "").suffix
        if suffix not in {".md", ".txt"}:
            raise ValueError("Unsupported file type")
        if len(content) > self.max_upload_bytes:
            raise ValueError("Document is too large")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Document must be UTF-8") from exc
        return text.replace("\r\n", "\n").replace("\r", "\n").encode()
