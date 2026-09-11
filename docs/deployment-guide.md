# Doc Agent 部署指南（内网服务器 / 单实例）

> 适用范围：当前架构（SQLite + 本地 `storage/`，后端 + 独立 Worker，**单实例**）。
> 适用场景：内网 Linux 服务器（Ubuntu 22.04+ / Debian 12+ 验证路径）。
> 不适用：公网生产、多实例高并发、PostgreSQL（替换路径见 `docs/architecture.md` §六）。
> 首次部署请按 §1→§6 顺序执行；日常升级见 §7。

## 0. 部署形态总览

```
                 ┌───────────────── nginx (80/443) ─────────────────┐
  浏览器 ────────▶│  /            → 静态文件 web/dist（前端构建产物）  │
                 │  /api/…       → 127.0.0.1:8000（uvicorn 后端）     │
                 └──────────────────────────────────────────────────┘
                                        │
         ┌──────────────────────────────┴─────────────┐
         │ doc-agent-backend.service (uvicorn:8000)    │  同一 SQLite 库
         │ doc-agent-worker.service  (run_worker.py)   │◀─┐ + 同一 storage/
         └─────────────────────────────────────────────┘  │
                                                          │
              doc_agent.db（WAL） + storage/（版本正文文件）
```

要点：
- **后端与 Worker 是两个独立进程，必须都运行**。只跑后端时：上传正常但知识索引不执行（任务面板停在「排队中」）。
- 前端是**静态产物**，由 nginx 直接服务；开发用的 Vite dev server 不要带上生产。
- 数据库与 storage 目录是**全部状态**，备份这两个即备份整站（见 §8）。

## 1. 前置依赖

| 依赖 | 版本要求 | 说明 |
|---|---|---|
| Python | 3.12+ | `uv` 会自动下载管理 |
| uv | 最新 | 安装：`curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | ^20.19 或 ≥22.12（Vite 要求） | 仅构建前端需要；构建产物可拷贝，目标机可不装 |
| nginx | 任意近版本 | 反代 + 静态文件 |

内网无外网时：提前在联网机器 `uv sync` 拉齐依赖并把整个项目目录（含 `.venv`）拷贝过去，
或配置内网 PyPI 镜像后执行（`pyproject.toml` 已默认阿里云镜像）。

## 2. 获取代码与依赖

```bash
sudo useradd -r -m -d /opt/doc-agent docagent   # 专用系统账号，服务不以 root 运行
sudo -u docagent git clone <仓库地址> /opt/doc-agent/app   # 或解压交付 zip
cd /opt/doc-agent/app

sudo -u docagent uv sync                        # 后端依赖（锁定于 uv.lock）
sudo -u docagent npm --prefix web ci            # 前端依赖（锁定于 package-lock.json）
```

## 3. 配置（.env）

```bash
sudo -u docagent cp .env.example .env
sudo -u docagent chmod 600 .env
sudo -u docagent vi .env
```

**生产必改项**（其余用默认值即可）：

| 变量 | 生产值 | 说明 |
|---|---|---|
| `ENVIRONMENT` | `production` | 同时启用 JWT 密钥强制检查（用默认密钥会启动失败） |
| `JWT_SECRET` | 64 位随机串 | `openssl rand -hex 32` 生成 |
| `DATABASE_URL` | `sqlite:////opt/doc-agent/data/doc_agent.db` | **绝对路径**；`sqlite:///` 后 4 个斜杠 + 绝对路径。放数据目录（非代码目录） |
| `STORAGE_DIR` | `/opt/doc-agent/data/storage` | 版本文件目录，与 db 同级便于整体备份 |
| `MODEL_PROVIDER` | `self` 或 `internal` | **不设置则默认 fake（离线演示回复）** |
| `SELF_AI_*` / `INTERNAL_API_*` | 按负责方提供 | provider 对应的 endpoint/api_key/model 三项缺一即启动报错 |
| `BACKEND_HOST` | `127.0.0.1` | 由 nginx 反代时保持本机；直连暴露再改 `0.0.0.0` |
| `CORS_ALLOWED_ORIGINS` | 仅跨域接入方需要 | JSON 数组，如 `["https://app.example.internal"]`；同源经 nginx 时留空 |
| `HF_HOME` | `/opt/doc-agent/hf-cache` | 向量模型缓存（**非 .env 项**，写进 systemd 环境，见 §4） |

```bash
sudo -u docagent mkdir -p /opt/doc-agent/data
```

**向量模型准备（内网离线必须）**：语义检索依赖 `BAAI/bge-small-zh-v1.5`，
下载失败会让检索/索引**抛错而非降级**（`docs/demo-handoff-2026-09-11-final.md` §六）。

```bash
# 联网机器执行（国内走镜像）：
HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 \
  uv run python scripts/prefetch_embeddings.py --cache-dir /tmp/hf-cache
# 把 /tmp/hf-cache 拷到服务器 /opt/doc-agent/hf-cache，并在 systemd 里设 HF_HOME
# 确实无模型可用时：EMBEDDING_ENABLED=false 退回纯关键词检索（功能可用，无向量召回）
```

## 4. systemd 服务

`/etc/systemd/system/doc-agent-backend.service`：

```ini
[Unit]
Description=Doc Agent API
After=network.target

[Service]
Type=simple
User=docagent
WorkingDirectory=/opt/doc-agent/app
Environment=HF_HOME=/opt/doc-agent/hf-cache
ExecStartPre=/opt/doc-agent/app/.venv/bin/python -m alembic upgrade head
ExecStart=/opt/doc-agent/app/.venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/doc-agent-worker.service`：

```ini
[Unit]
Description=Doc Agent background worker
After=network.target doc-agent-backend.service
Requires=doc-agent-backend.service

[Service]
Type=simple
User=docagent
WorkingDirectory=/opt/doc-agent/app
Environment=HF_HOME=/opt/doc-agent/hf-cache
ExecStart=/opt/doc-agent/app/.venv/bin/python run_worker.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now doc-agent-backend doc-agent-worker
curl -s http://127.0.0.1:8000/api/health   # 期望 {"status":"ready"}
```

说明：`.env` 由应用自行读取（工作目录下），无需写进 systemd；
`ExecStartPre` 保证每次启动自动跑迁移，多实例部署时要去掉（本方案仅单实例）。

## 5. 初始化数据与账号

```bash
cd /opt/doc-agent/app

# 正式管理员（交互输入密码，不要用演示账号）
sudo -u docagent .venv/bin/python scripts/bootstrap_admin.py --username <管理员名>
# 或按角色建号：
sudo -u docagent .venv/bin/python scripts/create_user.py --username <名字> --role user|reviewer|admin

# 演示/试用环境可灌合成数据（幂等，可重复跑）：
sudo -u docagent .venv/bin/python scripts/seed_demo.py
sudo -u docagent .venv/bin/python scripts/seed_roles.py
```

**上线检查**：确认正式环境不存在演示账号（`demo/shangji/xiashu`，密码据 `scripts/seed_roles.py` 顶部）。
管理页「用户与角色」可停用/改角色；停用后其 token 在 30 分钟有效期外无法再登录。

## 6. 前端构建与 nginx

```bash
cd /opt/doc-agent/app
sudo -u docagent npm --prefix web run build     # 产出 web/dist/
```

`/etc/nginx/sites-available/doc-agent`：

```nginx
server {
    listen 80;
    server_name doc-agent.internal;          # 按实际域名/主机名改

    client_max_body_size 12m;                # 上传限制 10MB + 余量（后端 MAX_UPLOAD_BYTES）

    root /opt/doc-agent/app/web/dist;
    index index.html;

    location / {                             # SPA：未命中文件回落 index.html
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;             # Agent 对话可能较慢（模型超时上限 300s 内按需调）
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/doc-agent /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

HTTPS：内网如有 CA，可加 `listen 443 ssl` 与证书；无则 HTTP 交付，但浏览器打印 PDF
与剪贴板等特性建议 HTTPS 环境（Chrome 部分能力在非安全上下文受限）。

## 7. 升级流程

```bash
cd /opt/doc-agent/app
sudo -u docagent .venv/bin/python scripts/backup.py --out /opt/doc-agent/data/backups   # 先备份
sudo -u docagent git pull                            # 或解压新交付包覆盖（保留 .env 与 data/）
sudo -u docagent uv sync
sudo -u docagent npm --prefix web ci && sudo -u docagent npm --prefix web run build
sudo systemctl restart doc-agent-backend doc-agent-worker
curl -s http://127.0.0.1:8000/api/health
```

迁移由 `ExecStartPre` 自动执行；如需手动回看：`uv run alembic current` / `upgrade head`。
**回滚**：切回旧代码 + `scripts/restore.py --from <备份目录>`（见 §8）。

## 8. 备份 / 恢复

```bash
# 备份（在线安全，无需停机）：产物含 db + storage + manifest
.venv/bin/python scripts/backup.py --out /opt/doc-agent/data/backups

# 恢复（先停服务）
sudo systemctl stop doc-agent-backend doc-agent-worker
.venv/bin/python scripts/restore.py --from /opt/doc-agent/data/backups/doc-agent-<时间戳> --dry-run
.venv/bin/python scripts/restore.py --from /opt/doc-agent/data/backups/doc-agent-<时间戳> --force
sudo systemctl start doc-agent-backend doc-agent-worker
```

建议 crontab 每日备份并异地留存：
`15 2 * * * cd /opt/doc-agent/app && .venv/bin/python scripts/backup.py --out /opt/doc-agent/data/backups`

## 9. 日常运维速查

| 操作 | 命令 |
|---|---|
| 健康检查 | `curl -s http://127.0.0.1:8000/api/health` |
| 查看日志 | `journalctl -u doc-agent-backend -f` / `journalctl -u doc-agent-worker -f` |
| 接口文档 | `http://<主机>/docs`（OpenAPI，中文标签） |
| 任务卡「排队中」 | Worker 未运行：`systemctl status doc-agent-worker` |
| 检索报错（非降级） | 模型缓存缺失：检查 `HF_HOME` 与目录内容；或显式 `EMBEDDING_ENABLED=false` |
| 上传 413 | nginx `client_max_body_size` 与后端 `MAX_UPLOAD_BYTES` 同时调整 |

## 10. 安全与合规清单（交付/评审用）

- [ ] `ENVIRONMENT=production` 且 `JWT_SECRET` 为随机值（默认密钥会启动失败，属保护）
- [ ] `.env` 权限 600、属主 docagent；不进版本库（`.gitignore` 已含）
- [ ] 演示账号已删除/停用；正式账号按最小权限建（admin 只给管理员）
- [ ] nginx 只暴露 80/443；8000 与 worker 不直接对外
- [ ] 模型接入确认为**内网端点**（涉密材料不出网；`MODEL_PROVIDER=internal`）
- [ ] 备份任务在跑且演练过一次恢复
- [ ] 数据目录（db+storage）在受控盘位，磁盘余量监控
- [ ] 明确单实例边界：不做多副本/负载均衡（SQLite 单写者）
