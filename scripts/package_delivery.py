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

前置：安装 uv（Python 包管理器）与 Node.js 20.19+/22.12+。

【本地试用 / 演示】
1. 解压本包到任意目录（路径避免中文，如 D:\\doc-agent）
2. 打开终端进入解压目录，执行：
     uv sync
     uv run python scripts/seed_demo.py
     uv run python scripts/seed_roles.py
     uv run python run_dev.py          （保持运行；Ctrl+C 停止；同时拉起后端与 worker）
3. 另开一个终端：
     npm --prefix web install
     npm --prefix web run dev
4. 浏览器打开 http://127.0.0.1:5173/ ，使用演示账号登录：
     demo / DemoPass-2026!      管理员
     shangji / ReviewPass-2026! 上级
     xiashu / StaffPass-2026!   下级（员工）

【服务器 / 内网部署】
完整步骤（systemd 服务、nginx 反代、生产构建、升级与备份、安全清单）见
docs/部署指南.md。要点：后端与 worker 必须同时运行；生产必须设置
ENVIRONMENT=production、JWT_SECRET、MODEL_PROVIDER 与 DATABASE_URL 绝对路径。

【离线环境】
本包默认 MODEL_PROVIDER=fake（离线演示模式，不调用外部模型）。
语义检索依赖向量模型（BAAI/bge-small-zh-v1.5），离线机器需先在联网机执行
scripts/prefetch_embeddings.py 并把缓存目录拷入（设 HF_HOME），详见部署指南 §3；
完全无模型时在项目根目录 .env 设置 EMBEDDING_ENABLED=false 退回纯关键词检索。

【测试】
     uv run pytest tests/unit tests/integration tests/evaluation -q
     npm --prefix web test -- --run
     npm --prefix web run test:e2e       （自动起隔离环境，需已装前端依赖）

更多说明见 README.md、docs/使用手册.md（操作手册）、
docs/部署指南.md（部署）、docs/架构说明.md（架构）。
"""


def git_paths(*extra_args: str) -> list[str]:
    # -z: NUL 分隔且不做八进制转义——否则中文文件名（如 docs/使用手册.md）会被
    # 转义成 \344\275\277... 导致路径解析失败、文件被静默漏出交付包
    result = subprocess.run(
        ["git", "ls-files", "-z", *extra_args],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return [item for item in result.stdout.split("\0") if item]


def collect_files() -> list[Path]:
    tracked = git_paths()
    untracked = git_paths("--others", "--exclude-standard")
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
    zip_path = args.output / f"DocAgent交付包-{stamp}.zip"

    files = collect_files()
    # 防回归：交付面文档必须进包（中文文件名的编码问题曾导致它们被静默漏掉）
    required = [
        "docs/文档导航.md", "docs/使用手册.md", "docs/部署指南.md", "docs/架构说明.md",
        "docs/运维手册.md", "docs/多角色迁移方案.md", "docs/交付记录-2026-09-11.md", "README.md",
    ]
    missing = [item for item in required if not (ROOT / item).is_file() or (ROOT / item) not in files]
    if missing:
        raise SystemExit(f"交付包缺少必选文档，拒绝打包：{missing}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr("启动说明.txt", START_README)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"交付包已生成：{zip_path}（{len(files) + 1} 个文件，{size_mb:.1f} MB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
