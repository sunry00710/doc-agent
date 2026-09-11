"""备份 doc_agent.db + storage/ 到带时间戳的归档目录。

用法（在项目根目录执行）：
    uv run python scripts/backup.py                # 备份到 backups/
    uv run python scripts/backup.py --out D:/bak   # 指定输出目录

注意：SQLite 使用在线备份 API（sqlite3 .backup），可在服务运行时安全备份，
无需停机。备份产物为目录，内含 doc_agent.db + storage/ + manifest.json。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def backup_database(source: Path, target: Path) -> None:
    # 在线备份：即使服务正在写，也能得到一致快照（WAL 模式下同样安全）
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        target_conn = sqlite3.connect(target)
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
    finally:
        source_conn.close()


def unique_target_dir(candidate: Path) -> Path:
    """同一秒内重复备份时自动加序号，避免覆盖已有归档。"""
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        alternative = candidate.with_name(f"{candidate.name}-{index}")
        if not alternative.exists():
            return alternative
    raise SystemExit(f"备份目录已存在且无法生成唯一名称: {candidate}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backup Doc Agent database and storage.")
    parser.add_argument("--out", type=Path, default=ROOT / "backups")
    parser.add_argument("--database", type=Path, default=ROOT / "doc_agent.db")
    parser.add_argument("--storage", type=Path, default=ROOT / "storage")
    args = parser.parse_args(argv)

    if not args.database.exists():
        raise SystemExit(f"database not found: {args.database}")

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target_dir = unique_target_dir(args.out / f"doc-agent-{stamp}")
    target_dir.mkdir(parents=True, exist_ok=False)

    backup_database(args.database, target_dir / "doc_agent.db")
    storage_copied = False
    if args.storage.exists():
        shutil.copytree(args.storage, target_dir / "storage")
        storage_copied = True

    manifest = {
        "created_at": stamp,
        "database": str(args.database),
        "storage": str(args.storage) if storage_copied else None,
        "note": "在线备份快照；恢复：uv run python scripts/restore.py --from <本目录>",
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"备份完成: {target_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
