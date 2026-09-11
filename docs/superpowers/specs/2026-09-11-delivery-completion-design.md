# 交付完善设计（三角色 / 异步索引 / 起草 / 导出 / 打包）

> 2026-09-11 夜间，基于 `docs/交接记录-2026-09-11晚间.md` 9.4 节遗留表。
> 目标：完成 P1/P2/P3 全部待办，产出可交付 zip + 三角色使用手册 + 架构交接文档。
> 决策已与用户逐项确认（AskUserQuestion ×2）。

## 0. 用户已确认的决策

| 议题 | 决定 |
|---|---|
| 用户管理程度 | 脚本 + 管理页用户列表（查看/改角色/停用） |
| 可读性 review 尺度 | 修明显问题，不动业务逻辑 |
| git | 本地提交到 `feature/doc-agent-foundation`，**不推送** |
| Job 队列 | 上传版本 → 事务内 enqueue `knowledge.ingest` → worker 异步消费；提供一键启动脚本 |
| PDF 导出 | 浏览器打印方案（`window.print()` + `@media print`），零后端依赖 |
| 交付包 | `package_delivery.py` 产出 zip 源码包（排除 .venv/node_modules/DB/日志） |

## 1. 三角色（P1）

**映射（沿用交接文档 Q1 结论，不改权限引擎）**：

| 业务角色 | 全局 Role | 项目 MembershipRole | 能力 |
|---|---|---|---|
| 管理员 | `admin` | （任意，可管理所有项目） | 管理页、用户管理、评审/治理 |
| 上级 | `reviewer` | `reviewer` 或 `owner` | 评审、批准、发起晋升治理 |
| 下级（员工） | `user` | `contributor` | 编辑、提交、评论、发起晋升申请、Agent 对话 |

**实现**：
1. `scripts/create_user.py`：`--username [--role user|reviewer|admin] [--password]`，交互式 getpass，仿 `bootstrap_admin.py`。
2. 后端新模块 `app/admin/router.py`（admin-only）：
   - `GET /api/admin/users` → 用户列表（id/username/role/is_active/created_at）
   - `PATCH /api/admin/users/{id}` → 改 role / is_active，防自降级（不能改自己）与防最后管理员被降级
3. `scripts/seed_roles.py`：幂等创建 `shangji`（reviewer）与 `xiashu`（user），加入演示项目为 reviewer / contributor；打印账号表。
4. 前端 `ManagementWorkspace`：新增「用户管理」区块（admin only）——列表 + 角色下拉 + 停用/启用；顶部三角色能力说明卡。

## 2. 三账号全流程 E2E（P1）

- 隔离 E2E seed 已建三账号（下详 §7）；新增 `web/e2e/three-roles.spec.ts`：
  - 管理员：能进「管理」页、看到用户管理区块
  - 上级：评审页可见、能批准晋升/评审动作（按钮级断言）
  - 下级：投稿/编辑可见；**批准/评审按钮不可见**；`/api/admin/users` 直连返回 403
- 断言按钮显隐而非只靠 UI 跳转，确保权限隔离真实。

## 3. 对比结果持久化（P2）

- `ComparisonView`：结果按 `docId + {a}..{b} + mode` 存 sessionStorage；
  切 tab 回来 restore（含选中版本对与模式）；**失败/错误态不还原**；查看者退出登录时随 token 清理策略一并清（沿用现有 logout 前缀清理思路）。
- 新增前端单测：切换后恢复、错误不恢复。

## 4. ruff（P2）

- 修 `tests/integration/test_quality_bound_source.py` 3 个未使用导入，`uv run ruff check app tests` 全绿。

## 5. Job 队列生产端（P3）

现状：`Worker` + `KnowledgeIngestionHandler` 完整；**唯一缺生产端**（`ingest_version` 的 API/脚本调用全是同步）。

**改动**：
1. `POST /api/documents/{id}/versions`（上传）：`create_version` 后，在**同一事务**内对该版本所属文档的项目空间（`KnowledgeSpaceKind.project`，若无则创建）执行
   `enqueue("knowledge.ingest", IngestionJobPayload(version_id, space_id), owner_id=上传者, idempotency_key=f"knowledge.ingest:{version_id}")`。
   - 版本不可变 → version_id 作幂等键天然正确
   - 事务提交后 Job 落库；worker 轮询消费
2. `run_worker.py` 不动（已可用）；新增 `scripts/dev_up.bat` / `dev_down.bat` 一键拉起后端+worker+前端。
3. `JobStatus` 面板：`App.tsx` 启动拉一次 → 改为 **15s 轮询**（页面可见时）；
4. 测试：现有"上传即检索可见"类测试改为**手动 `worker.run_once()`** 或 monkeypatch enqueue 后同步断言 Job 落库 + handler 单测已有覆盖。涉及文件：`tests/integration/test_jobs.py`、`test_search_citations.py`、`test_knowledge_isolation.py` 等中经 API 上传的用例逐个排查。

**降级语义**（写进使用手册）：worker 未启动时上传成功但暂不可检索，Job 面板显示"排队中"；启动 worker 后自动补索引（Job 本身持久化，天然补偿）。

## 6. Agent 起草（P3）

**边界原则延续**：Agent 只建议，不改稿；落库必经人工确认。

**后端**（`app/quality/tools.py`）：
- `DraftInput`：`title` + `content`（≥50 字）+ `notes?`
- `draft_document` 工具：非 mutating；handler 原样回显并做基本规范性检查（内容非空、含标题），产出存入 trace/result 返回
- `prompts.py`：能力清单 +1 条「可以起草新文档草稿，产物为文本，由用户确认后保存为新版本」

**前端**（`AgentWorkspace`）：回复的 tool trace 中出现 `draft_document` 成功 → 渲染「保存为草稿」按钮 → 点击调用 `onApplySuggestion` 链路（`DocumentHub` 已有）→ 写入编辑器 draft，用户再点「保存为新版本」。`DocumentHub` 中已有 `onApplySuggestion` 回填能力，复用即可；工作台视图（无绑定文档）不可保存，提示去文档页。

## 7. PDF 导出（P3）

- `DocumentHub` 工具条（正文 tab）：「导出 PDF」→ `window.print()`。
- CSS `@media print`：隐藏侧栏/版式导航/工具条/版本列/按钮，仅保留文档标题 + 正文（`pre` 保留换行）+ 页脚日期；预览用浏览器打印对话框（Chromium 可另存 PDF）。
- 无新依赖。

## 8. 交付打包（交付项）

- `README.md`（根目录，一页纸）：是什么 / 快速启动（uv、node、seed、dev_up.bat）/ 测试怎么跑 / 目录地图 / 文档索引。
- `docs/使用手册`：更新 `使用手册.md` 为三角色分角色操作指南 + 完整演示脚本（登录→上传→评审→晋升→对比→导出→起草）。
- `docs/架构与交接文档`：模块地图、数据流（上传→索引→检索→Agent）、关键约定（确认-执行、幂等、版本不可变、Job 语义）、接手 FAQ。
- `scripts/package_delivery.py`：`git archive` 或清单复制 → `dist/doc-agent-delivery-YYYYMMDD.zip`，排除 `.venv/ node_modules/ doc_agent.db* storage/ __pycache__/ .pytest_cache/ test-results/`；zip 内附 `启动说明.txt`。

## 9. 测试基线（完成标准）

| 套件 | 现状 | 目标 |
|---|---|---|
| 后端 pytest | 208 passed, 1 skipped | 全绿 + 新增用例 |
| 前端 vitest | 34 passed | 全绿 + 新增用例 |
| E2E | 7 passed | 全绿 + 新增 2 spec（三账号、对比持久化） |
| tsc | 干净 | 干净 |
| ruff | 3 errors | 0 |

## 10. 实施顺序

1. ruff（速胜）→ 2. 对比持久化 → 3. 三角色（脚本→API→UI）→ 4. E2E 种子扩展 + 三账号 spec → 5. 异步索引 → 6. 起草 → 7. PDF → 8. 可读性 review → 9. 文档 + 打包 → 10. 全量回归 + 本地提交。
