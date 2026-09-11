"""从 scripts/backup.py 生成的归档目录恢复 doc_agent.db 与 storage/。

用法（恢复前先停止后端与 Worker，避免恢复过程中仍有进程写库）：
    uv run python scripts/restore.py --from backups/doc-agent-20260911-120000 --dry-run
    uv run python scripts/restore.py --from backups/doc-agent-20260911-120000
    uv run python scripts/restore.py --from <dir> --force   # 目标已存在时覆盖

安全策略：
- 目标数据库已存在且未加 --force 时直接拒绝，绝不静默覆盖。
- 加 --force 时，先把现有 doc_agent.db / storage 另存为
  *.pre-restore-<时间戳>，再写入归档内容。
- 恢复后清理目标库残留的 -wal/-shm，并跑 PRAGMA integrity_check 校验。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backup import backup_database, unique_target_dir


def read_manifest(archive: Path) -> dict:
    manifest_path = archive / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def integrity_check(database: Path) -> str:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def table_count(database: Path) -> int:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "select count(*) from sqlite_master "
            "where type='table' and name not like 'sqlite_%'"
        ).fetchone()
        return int(row[0])
    finally:
        connection.close()


def restore_database(source: Path, target: Path) -> None:
    """用 SQLite 在线备份 API 覆盖目标库，避免半写入的坏文件。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        target_conn = sqlite3.connect(target)
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
    finally:
        source_conn.close()


def remove_sidecars(database: Path) -> list[Path]:
    removed: list[Path] = []
    for suffix in ("-wal", "-shm"):
        sidecar = database.with_name(database.name + suffix)
        if sidecar.exists():
            sidecar.unlink()
            removed.append(sidecar)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restore Doc Agent database and storage from a backup archive."
    )
    parser.add_argument("--from", dest="archive", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=ROOT / "doc_agent.db")
    parser.add_argument("--storage", type=Path, default=ROOT / "storage")
    parser.add_argument(
        "--force",
        action="store_true",
        help="目标已存在时覆盖（覆盖前自动另存 .pre-restore-<时间戳> 快照）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的动作")
    args = parser.parse_args(argv)

    archive_db = args.archive / "doc_agent.db"
    archive_storage = args.archive / "storage"
    if not archive_db.exists():
        raise SystemExit(f"归档中缺少 doc_agent.db: {args.archive}")

    source_state = integrity_check(archive_db)
    if source_state != "ok":
        raise SystemExit(f"归档数据库完整性校验失败: {source_state}")

    manifest = read_manifest(args.archive)
    target_exists = args.database.exists()
    storage_exists = archive_storage.exists()
    print(f"归档: {args.archive}")
    print(
        f"归档时间: {manifest.get('created_at', '未知')} | 表数量: {table_count(archive_db)}"
    )
    print(f"目标数据库: {args.database}（{'覆盖' if target_exists else '新建'}）")
    print(
        f"目标存储目录: {args.storage}（{'覆盖' if args.storage.exists() else '新建'}；"
        f"归档{'含' if storage_exists else '不含'} storage/）"
    )
    if args.dry_run:
        print("dry-run：未写入任何文件")
        return 0

    if target_exists and not args.force:
        raise SystemExit(
            f"目标数据库已存在: {args.database}\n"
            "确认覆盖请加 --force（覆盖前会自动另存 .pre-restore-<时间戳> 快照）。"
        )

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    if target_exists:
        snapshot = unique_target_dir(
            args.database.with_name(f"{args.database.name}.pre-restore-{stamp}")
        )
        backup_database(args.database, snapshot)
        print(f"已另存现有数据库: {snapshot}")
    if args.storage.exists():
        storage_snapshot = unique_target_dir(
            args.storage.with_name(f"{args.storage.name}.pre-restore-{stamp}")
        )
        shutil.move(str(args.storage), str(storage_snapshot))
        print(f"已另存现有存储目录: {storage_snapshot}")

    restore_database(archive_db, args.database)
    for sidecar in remove_sidecars(args.database):
        print(f"已清理残留: {sidecar}")
    if storage_exists:
        shutil.copytree(archive_storage, args.storage)
        print(f"已恢复存储目录: {args.storage}")

    state = integrity_check(args.database)
    if state != "ok":
        raise SystemExit(f"恢复后完整性校验失败: {state}")
    print(
        f"恢复完成：{args.database}"
        f"（表数量 {table_count(args.database)}，integrity_check=ok）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
