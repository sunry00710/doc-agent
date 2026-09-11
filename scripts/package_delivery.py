"""打交付 zip 包。

用法：
    uv run python scripts/package_delivery.py [--output dist]

内容：当前 git 仓库的已跟踪文件（HEAD）+ 工作区中新增未跟踪的文件，
排除 .venv、node_modules、数据库、storage 产物、缓存与测试产物。
zip 内附「启动说明.txt」。

注意：基于「已跟踪 + git ls-files --others（排除忽略项）」收集，
不包含 .env（可能含密钥）——交付包用 .env.example 代替。
"""
from __future__ import annotations

import argparse
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIRS = {
    ".venv", "node_modules", "dist", "__pycache__", ".pytest_cache",
    ".ruff_cache", "test-results", "playwright-report", "storage",
    ".git", "docs/superpowers",
}
EXCLUDE_FILES = {"doc_agent.db", "doc_agent.db-shm", "doc_agent.db-wal"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log"}

START_README = """Doc Agent 交付包 · 启动说明
================================

前置：安装 uv（Python 包管理器）与 Node.js 18+。
推荐在一台干净的 Windows 机器上按以下步骤验证：

1. 解压本包到任意目录（路径避免中文，如 D:\\doc-agent）
2. 打开终端进入解压目录，执行：
     uv sync
     uv run python scripts/seed_demo.py
     uv run python scripts/seed_roles.py
     uv run python run_dev.py          （保持运行；Ctrl+C 停止）
3. 另开一个终端：
     npm --prefix web install
     npm --prefix web run dev
4. 浏览器打开 http://127.0.0.1:5173/ ，使用演示账号登录：
     demo / DemoPass-2026!      管理员
     shangji / ReviewPass-2026! 上级
     xiashu / StaffPass-2026!   下级（员工）

离线环境：本包默认 MODEL_PROVIDER=fake（离线演示模式，不调用外部模型）。
语义检索依赖的向量模型（BAAI/bge-small-zh-v1.5）首次使用需要网络；
无网络环境请在 web/.env 或运行环境中设置 EMBEDDING_ENABLED=false
退回纯关键词检索（功能可用，只是没有向量召回）。

日常测试：
     uv run pytest tests/unit tests/integration tests/evaluation -q
     npm --prefix web test -- --run
     npm --prefix web run test:e2e       （自动起隔离环境，需已装前端依赖）

更多说明见 README.md 与 docs/demo-usage-guide.md。
"""


def collect_files() -> list[Path]:
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    paths: list[Path] = []
    for rel in sorted({line for line in [*tracked, *untracked] if line.strip()}):
        path = ROOT / rel
        if not path.is_file():
            continue
        parts = set(Path(rel).parts)
        if parts & EXCLUDE_DIRS:
            continue
        if path.name in EXCLUDE_FILES or path.suffix in EXCLUDE_SUFFIXES:
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Package the delivery zip.")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    zip_path = args.output / f"doc-agent-delivery-{stamp}.zip"

    files = collect_files()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr("启动说明.txt", START_README)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"交付包已生成：{zip_path}（{len(files) + 1} 个文件，{size_mb:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
