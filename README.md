# Doc Agent · 企业文档质量管控 Agent

[![CI](https://github.com/sunry00710/doc-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/sunry00710/doc-agent/actions/workflows/ci.yml)
[![E2E](https://github.com/sunry00710/doc-agent/actions/workflows/e2e.yml/badge.svg)](https://github.com/sunry00710/doc-agent/actions/workflows/e2e.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![Node](https://img.shields.io/badge/Node-20.19%2B%20%7C%2022.12%2B-339933)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED)

一个可运行的企业文档质量管控工作台。核心主张是 **「AI 是质量门，不是作者」**：
Agent 基于绑定的不可变版本做检查、改写建议、版本对比、批注与起草，所有断言必须带
原文引文溯源；人类始终保留最终裁决权。

演示模式（`FakeProvider`）**完全离线可跑，无需任何模型密钥**，一条命令即可本地体验全流程。

## 这个项目解决什么问题

企业正式文档（制度、审计文书、合同）的写作—评审—归档存在三个痛点：

| 痛点 | 本项目做法 |
|---|---|
| AI 全自动撰写正式文档不可接受，但人工逐字校对成本高 | AI 只标记**高风险候选问题**，人类裁决；写操作需显式确认 + 幂等键 |
| AI 输出无法追溯，出错不知从何改起 | 每个断言绑定**字符偏移 + SHA256 校验**的原文引文，宁可声明「未找到依据」也不给错引文 |
| 改了文档但索引/评审还是旧的，版本混乱 | 文档版本一经创建**不可变**，修改 = 上传新版本；评审工作流覆盖「提交 → 评审 → 批准 → 晋升 → 索引」 |

## 技术亮点

| 能力 | 实现 |
|---|---|
| 混合检索 | SQLite FTS5（BM25）关键词召回 + 向量召回，用 **RRF** 融合排序（不依赖两路分数量纲） |
| 权限治理 | **检索前**过滤（而非检索后），个人 / 项目 / 共享 / 规范四类知识空间；避免「Top-K 全无权限 → 静默返回空」 |
| 引文溯源 | 字符偏移切片 + SHA256 版本绑定 + 切片逐字符校验，任一步失败即报错而非给错引文 |
| Agent 工具安全 | 变更类工具必须带 `confirmed=true` + 幂等键，幂等存储跨请求生效 |
| 持久化任务队列 | 自研 job 队列（心跳、重试、stale 回收），上传即入队、worker 未运行自动补偿 |
| 可验证性 | 228 个 pytest 用例 + Playwright E2E + ruff / tsc 全绿 CI |

## 界面预览

| Agent 工作台（右栏是检索到的引文证据） | 知识库检索（命中片段带原文引文） |
| --- | --- |
| ![Agent 工作台](docs/images/02-agent-workspace.png) | ![知识库检索](docs/images/04-knowledge-search.png) |

| 文档版本与质量门 | 登录 |
| --- | --- |
| ![文档](docs/images/03-documents.png) | ![登录](docs/images/01-login.png) |

## 快速开始

### 方式一：Docker（推荐，零依赖）

```bash
git clone https://github.com/sunry00710/doc-agent.git
cd doc-agent
docker compose up -d --build
```

打开 **<http://localhost:8000>** 即可。首次启动会自动建表并灌入演示数据。

```bash
docker compose logs -f      # 看日志
docker compose down         # 停止（数据保留）
docker compose down -v      # 停止并清空数据
```

> 容器内已关闭向量召回（`EMBEDDING_ENABLED=false`），检索走 SQLite FTS5 关键词 + 引文溯源，
> 避免首次启动下载模型。功能完整，只是没有向量召回这一路。

### 方式二：本地开发（Windows）

```bash
# 1. 后端依赖（需要 uv 与 Node.js 20.19+/22.12+，Vite 要求）
uv sync

# 2. 建库建表（首次必跑：种子脚本不会自动建表）
uv run alembic upgrade head

# 3. 灌入演示数据（幂等，可重复执行）
uv run python scripts/seed_demo.py
uv run python scripts/seed_roles.py       # 补齐三角色账号（管理员/上级/下级）
uv run python scripts/seed_knowledge.py   # 8 份制度文档：知识库检索与引文演示需要

# 4. 启动后端 + 后台 worker（Ctrl+C 停止）
uv run python run_dev.py

# 5. 另开终端启动前端
npm --prefix web install
npm --prefix web run dev
```

打开 `http://127.0.0.1:5173/`，用 `scripts/seed_roles.py` 输出的账号登录：

| 账号 | 密码 | 角色 | 能做什么 |
|---|---|---|---|
| `demo` | `DemoPass-2026!` | 管理员 | 管理用户与项目成员、评审、知识库治理 |
| `shangji` | `ReviewPass-2026!` | 上级 | 审核与批准下属提交、发起晋升治理 |
| `xiashu` | `StaffPass-2026!` | 下级（员工） | 编辑提交、评论、向知识库投稿 |

> 以上密码仅用于本地演示，部署到共享环境前必须更换。

### 无外网 / 无法访问 HuggingFace 时的离线演示

语义检索默认开启（`EMBEDDING_ENABLED=true`），首次建索引会从 HuggingFace 拉取
`BAAI/bge-small-zh-v1.5`。无外网环境下这一步会失败，导致文档索引任务报错。
离线演示请显式关闭向量召回：

```bash
cp .env.example .env
# 编辑 .env：EMBEDDING_ENABLED=false
```

此时检索走 SQLite FTS5 关键词召回 + 引文溯源，功能可用，只是不再有向量召回
（`mode=hybrid` 在没有可用向量时退化为关键词检索）。这是有意的降级设计，不是缺陷。
若能访问镜像，也可改走镜像而不关向量：`HF_ENDPOINT=https://hf-mirror.com`。

## 常用命令

| 用途 | 命令 |
|---|---|
| 后端测试 | `uv run pytest tests/unit tests/integration tests/evaluation -q` |
| 前端测试 | `npm --prefix web test -- --run` |
| E2E 测试（自动起隔离环境） | `npm --prefix web run test:e2e` |
| 类型检查 | `cd web && npx tsc --noEmit` |
| 代码检查 | `uv run ruff check app tests` |
| 备份 / 恢复数据库 | `uv run python scripts/backup.py` / `uv run python scripts/restore.py` |

## 目录地图

```
app/
  main.py            应用装配（路由、异常、provider、工具注册表）
  core/              配置、错误信封、密码哈希
  identity/          用户与全局角色（user / reviewer / admin）、登录
  admin/             管理员接口：用户列表与角色调整
  projects/          项目、项目成员、项目级权限（contributor / reviewer / owner）
  documents/         文档与不可变版本、文件存储与校验
  reviews/           评审状态机、批注与返修
  quality/           质量工具（检查/改写/对比/评审/评判/起草）、提示词、写作契约
  knowledge/         知识空间、切块、检索（FTS+向量）、晋升治理、索引任务
  jobs/              持久化任务队列（生产端/worker/心跳/重试）
  providers/         模型接入（fake / self）
web/                 React 前端（Vite + TS）
  src/app/           壳与导航、全局状态（App.tsx）
  src/features/      各功能工作面（agent/documents/knowledge/reviews/comparison/management…）
  e2e/               Playwright E2E（自起隔离后端+前端+worker，独立端口）
docker/              容器入口与 nginx 配置（前端托管 + /api 反向代理）
tests/               后端测试（unit / integration / evaluation）
scripts/             种子、账号、备份、打包脚本
docs/                使用手册、架构说明、部署指南、开发指南、运维手册
```

## 关键约定（新人必读）

- **不可变版本**：文档版本一经创建不可修改（`DocumentVersion` 有 before_update 钩子拒绝更新）；
  修改 = 上传新版本。
- **确认-执行**：Agent 的变更类工具必须带 `confirmed=true` + 幂等键才执行；
  幂等存储在应用级 ToolRegistry 上（跨请求生效）。
- **上传即入队**：上传新版本会在同一事务里给 `knowledge.ingest` 任务入队（幂等键 = 版本 ID），
  由 worker 异步建索引。worker 未运行时上传仍成功、Job 面板显示「排队中」，
  启动 worker 后自动补偿。
- **权限双层**：全局角色（admin/reviewer/user）× 项目角色（owner/reviewer/contributor），
  后端 `require_project_permission` 是唯一权威，前端只做入口显隐。
  全局角色判断必须经 `app/identity/roles.py` / `web/src/app/roles.ts`（多角色演进接缝）。
- **模型接入**：`MODEL_PROVIDER=fake|self`；fake 为离线演示（语义对比自动降级为
  启发式并如实标注引擎），`self` 接任意 OpenAI 兼容端点，配 `.env` 即可（见 `.env.example`）。

## 文档索引

| 文档 | 内容 |
|---|---|
| `docs/使用手册.md` | 三角色操作手册 + 完整演示脚本 |
| `docs/架构说明.md` | 模块地图、数据流、关键机制细节 |
| `docs/部署指南.md` | **服务器部署**：systemd、nginx、升级、备份、安全清单 |
| `docs/开发指南.md` | **参与开发**：代码约定、扩展步骤（加端点/工具/任务/迁移）、技术债 |
| `docs/多角色迁移方案.md` | 多角色演进方案（角色判断已收敛到 roles.py / roles.ts） |
| `docs/运维手册.md` | 备份恢复、日志、常见故障处理 |

## 许可

MIT License。演示数据为脚本生成的虚构内容，不含任何真实企业文档。
