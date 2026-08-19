from pathlib import Path

import pytest

import app.documents.storage as storage_module
from app.core.config import Settings
from app.documents.storage import FileStorage


def storage(tmp_path: Path, max_upload_bytes: int = 1024) -> FileStorage:
    return FileStorage(
        Settings(
            environment="test",
            storage_dir=tmp_path / "storage",
            max_upload_bytes=max_upload_bytes,
        )
    )


def test_storage_key_is_generated_and_never_contains_user_filename(tmp_path: Path):
    file_storage = storage(tmp_path)

    stored = file_storage.store("../annual report.md", b"draft")

    assert "annual report" not in stored.storage_key
    assert ".." not in stored.storage_key
    assert stored.storage_key.split("/")[0]
    assert file_storage.read(stored.storage_key) == b"draft"


def test_traversal_filename_cannot_escape_storage_root(tmp_path: Path):
    file_storage = storage(tmp_path)
    outside = tmp_path / "escaped.md"

    stored = file_storage.store("../../escaped.md", b"draft")

    assert not outside.exists()
    assert file_storage.path_for(stored.storage_key).is_relative_to(file_storage.root)


@pytest.mark.parametrize("filename", ["draft.pdf", "draft", "draft.MD"])
def test_only_markdown_and_text_extensions_are_accepted(tmp_path: Path, filename: str):
    with pytest.raises(ValueError, match="Unsupported file type"):
        storage(tmp_path).store(filename, b"draft")


def test_invalid_utf8_and_oversize_content_are_rejected(tmp_path: Path):
    file_storage = storage(tmp_path, max_upload_bytes=3)

    with pytest.raises(ValueError, match="UTF-8"):
        file_storage.store("draft.md", b"\xff")
    with pytest.raises(ValueError, match="too large"):
        file_storage.store("draft.md", b"1234")


def test_store_replaces_a_durable_temp_file_without_leaving_temps(tmp_path: Path, monkeypatch):
    file_storage = storage(tmp_path)
    replaced: list[tuple[Path, Path]] = []
    original_replace = storage_module.os.replace

    def recording_replace(source: Path, destination: Path) -> None:
        replaced.append((Path(source), Path(destination)))
        original_replace(source, destination)

    monkeypatch.setattr(storage_module.os, "replace", recording_replace)

    stored = file_storage.store("draft.md", b"draft")

    assert len(replaced) == 1
    temp_path, final_path = replaced[0]
    assert temp_path.parent == final_path.parent
    assert final_path == file_storage.path_for(stored.storage_key)
    assert final_path.read_bytes() == b"draft"
    assert not temp_path.exists()
    assert not list(file_storage.root.rglob("*.tmp"))


def test_normalizes_line_endings_before_storage_and_hashing(tmp_path: Path):
    file_storage = storage(tmp_path)

    crlf = file_storage.store("one.md", b"a\r\nb\r")
    lf = file_storage.store("two.txt", b"a\nb\n")

    assert crlf.content == b"a\nb\n"
    assert crlf.content_sha256 == lf.content_sha256
    assert file_storage.read(crlf.storage_key) == b"a\nb\n"
