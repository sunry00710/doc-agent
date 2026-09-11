from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.backup import main as backup_main
from scripts.restore import integrity_check
from scripts.restore import main as restore_main


def _create_database(path: Path, rows: list[tuple[int, str]]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("create table notes (id integer primary key, body text not null)")
        connection.executemany("insert into notes (id, body) values (?, ?)", rows)
        connection.commit()
    finally:
        connection.close()


def _append_note(path: Path, row: tuple[int, str]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("insert into notes (id, body) values (?, ?)", row)
        connection.commit()
    finally:
        connection.close()


def _notes(path: Path) -> list[tuple[int, str]]:
    connection = sqlite3.connect(path)
    try:
        return [(int(row[0]), str(row[1])) for row in connection.execute("select id, body from notes order by id")]
    finally:
        connection.close()


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    database = tmp_path / "doc_agent.db"
    storage = tmp_path / "storage"
    (storage / "originals").mkdir(parents=True)
    (storage / "originals" / "v1.md").write_text("版本一", encoding="utf-8")
    _create_database(database, [(1, "备份前")])
    return database, storage, tmp_path / "backups"


def _backup(database: Path, storage: Path, out: Path) -> Path:
    before = set(out.glob("doc-agent-*"))
    assert (
        backup_main(["--out", str(out), "--database", str(database), "--storage", str(storage)])
        == 0
    )
    created = sorted(set(out.glob("doc-agent-*")) - before)
    assert len(created) == 1
    archive = created[0]
    assert integrity_check(archive / "doc_agent.db") == "ok"
    return archive


def test_backup_copies_database_and_storage(tmp_path: Path) -> None:
    database, storage, out = _workspace(tmp_path)

    archive = _backup(database, storage, out)

    assert _notes(archive / "doc_agent.db") == [(1, "备份前")]
    assert (archive / "storage" / "originals" / "v1.md").read_text(encoding="utf-8") == "版本一"
    manifest = (archive / "manifest.json").read_text(encoding="utf-8")
    assert "restore.py" in manifest
    assert "doc_agent.db" in manifest


def test_repeated_backup_does_not_overwrite_earlier_archive(tmp_path: Path) -> None:
    database, storage, out = _workspace(tmp_path)

    first = _backup(database, storage, out)
    _append_note(database, (2, "第二次备份"))
    second = _backup(database, storage, out)

    assert first != second
    assert _notes(first / "doc_agent.db") == [(1, "备份前")]
    assert _notes(second / "doc_agent.db") == [(1, "备份前"), (2, "第二次备份")]


def test_dry_run_reports_plan_without_writing(tmp_path: Path) -> None:
    database, storage, out = _workspace(tmp_path)
    archive = _backup(database, storage, out)
    _append_note(database, (2, "备份后新增"))

    assert (
        restore_main(
            [
                "--from",
                str(archive),
                "--database",
                str(database),
                "--storage",
                str(storage),
                "--dry-run",
            ]
        )
        == 0
    )
    assert _notes(database) == [(1, "备份前"), (2, "备份后新增")]


def test_restore_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    database, storage, out = _workspace(tmp_path)
    archive = _backup(database, storage, out)
    _append_note(database, (2, "备份后新增"))

    with pytest.raises(SystemExit, match="--force"):
        restore_main(
            [
                "--from",
                str(archive),
                "--database",
                str(database),
                "--storage",
                str(storage),
            ]
        )
    assert _notes(database) == [(1, "备份前"), (2, "备份后新增")]


def test_restore_rolls_back_to_snapshot_and_cleans_sidecars(tmp_path: Path) -> None:
    database, storage, out = _workspace(tmp_path)
    archive = _backup(database, storage, out)
    _append_note(database, (2, "备份后新增"))
    (storage / "originals" / "v1.md").unlink()
    stale_wal = database.with_name(database.name + "-wal")
    stale_wal.write_bytes(b"stale")

    assert (
        restore_main(
            [
                "--from",
                str(archive),
                "--database",
                str(database),
                "--storage",
                str(storage),
                "--force",
            ]
        )
        == 0
    )

    assert _notes(database) == [(1, "备份前")]
    assert (storage / "originals" / "v1.md").read_text(encoding="utf-8") == "版本一"
    assert not stale_wal.exists()
    assert integrity_check(database) == "ok"
    assert list(tmp_path.glob("doc_agent.db.pre-restore-*"))
    assert list(tmp_path.glob("storage.pre-restore-*"))
