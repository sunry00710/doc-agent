# syntax=docker/dockerfile:1

# ---------- Stage 1: 构建前端静态产物 ----------
FROM node:22-slim AS web-builder
WORKDIR /build/web
COPY web/package.json web/package-lock.json* ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---------- Stage 2: Python 运行时 + nginx ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    DEBIAN_FRONTEND=noninteractive

# nginx 用于托管前端静态文件 + 反向代理 /api（保持前后端同源，无需 CORS）
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx \
 && rm -rf /var/lib/apt/lists/*

# uv：与项目 pyproject.toml / uv.lock 使用同一套解析器
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /usr/local/bin/

WORKDIR /app

# 先装依赖，利用层缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 再拷源码
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini run_dev.py run_worker.py ./
COPY scripts/ ./scripts/

# 前端产物交给 nginx
COPY --from=web-builder /build/web/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/default

# 数据落盘位置：SQLite + 上传文件
ENV DATABASE_URL=sqlite:////data/doc_agent.db \
    STORAGE_DIR=/data/storage \
    BACKEND_HOST=127.0.0.1 \
    BACKEND_PORT=8000 \
    MODEL_PROVIDER=fake \
    EMBEDDING_ENABLED=false \
    SEED_DEMO=true \
    JWT_SECRET=change-me-before-exposing

RUN mkdir -p /data/storage

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 80
VOLUME ["/data"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3).status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
