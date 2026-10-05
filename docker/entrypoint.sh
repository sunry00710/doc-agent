#!/bin/sh
# Doc Agent 容器入口：建表 → 播种 → 起 nginx + 后端 + worker
set -e

echo "[entrypoint] 建表 ..."
uv run alembic upgrade head

if [ "${SEED_DEMO:-true}" = "true" ]; then
  echo "[entrypoint] 灌入演示数据（幂等，可关掉：SEED_DEMO=false）"
  uv run python scripts/seed_demo.py
  uv run python scripts/seed_roles.py
  uv run python scripts/seed_knowledge.py
fi

echo "[entrypoint] 启动 nginx（:80 托管前端 + 反代 /api）"
nginx

echo "[entrypoint] 启动后端 + worker（run_dev.py 自带子进程管理与优雅退出）"
exec uv run python run_dev.py
