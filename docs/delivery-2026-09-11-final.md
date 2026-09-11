# Doc Agent 交付记录（2026-09-11 交付版 · 最终）

> 前序文档：`docs/demo-handoff-2026-09-11.md`（上午验收）、`-final.md`（下午改造）、
> `-evening.md`（晚间基线）。**本文件记录交付完成的全部改动与验证证据**。

## 〇、工作区状态

```
项目根: D:\workspace1\doc-agent-worktrees\foundation
分支: feature/doc-agent-foundation（仅本地，未 push）
交付包: dist/doc-agent-delivery-20260911.zip（scripts/package_delivery.py 生成）
启动: 见根目录 README.md（uv sync → 两个种子脚本 → run_dev.py → npm dev）
```

## 一、本次交付完成的待办（对应 9.4 遗留表）

| 优先 | 项 | 完成内容 |
|---|---|---|
| P1 | 三角色 | 全局角色映射落地：管理员=admin、上级=reviewer、下级=user（员工）；新增 `scripts/create_user.py`（交互建号）、`app/admin/router.py`（GET/PATCH /api/admin/users，admin-only，防自降级/防移除最后管理员）、管理页「用户与角色」tab（列表/改角色/停用启用 + 三角色能力说明）、`scripts/seed_roles.py`（幂等补齐 shangji/xiashu 演示账号） |
| P1 | 三账号全流程 | 新增 `web/e2e/three-roles.spec.ts`：三类账号登录、能力显隐、管理 API 403 直连断言 |
| P2 | 对比持久化 | `ComparisonView` 结果按 文档+版本对+模式 存 sessionStorage，切 tab 恢复；选择变化清空旧结果；4 个新单测 |
| P2 | 对比 E2E | 新增 `web/e2e/comparison.spec.ts`（引擎徽章/变更卡片/切 tab 恢复/切换清空）；seed 补第二版本 |
| P2 | ruff | `tests/integration/test_quality_bound_source.py` 未使用导入清零，`ruff check app tests` 全绿 |
| P3 | Job 队列生产端 | 上传版本同事务入队 `knowledge.ingest`（幂等键=版本 ID，`app/knowledge/ingestion_queue.py`）；Job 面板 15s 轮询；E2E 隔离环境加入 worker 进程；3 个新集成测试 |
| P3 | PDF 导出 | 文档正文页「导出 PDF」→ `window.print()` + `@media print` 仅打印标题与正文层（无新依赖） |
| P3 | Agent 起草 | `draft_document` 工具（非 mutating，只产出文本）+ 离线演示链路（FakeProvider 识别起草意图）+ 前端「保存为草稿」按钮（回填编辑器，人工确认后走既有「保存为新版本」落库）+ prompt 能力边界（PROMPT_VERSION=quality-v3） |
| 交付 | 文档 | `README.md`（60 秒启动/命令/目录地图）、`docs/demo-usage-guide.md`（三角色操作手册）、`docs/architecture.md`（架构与关键机制）、`docs/deployment-guide.md`（服务器/内网部署：systemd/nginx/升级/备份/安全清单——交付检查时补充） |
| 交付 | 打包 | `scripts/package_delivery.py` → zip（排除 .venv/node_modules/DB/storage/缓存/.env，附「启动说明.txt」；含锁文件 uv.lock/package-lock.json、全部 alembic 迁移、备份恢复脚本） |

## 二、代码可读性审查（新人视角）+ 顺手修复

审查结论：工程纵深高于平均（错误信封、事务文件补偿、状态机、E2E 隔离），
主要问题集中在模块命名与隐形接线。已修复：

**真实缺陷（非风格）**
1. **跨请求幂等失效**：`app.state.agent_tools` 从未被赋值，`get_runner` 每次请求
   新建 ToolRegistry + InMemoryIdempotencyStore → 确认-执行的幂等去重只在单请求内有效。
   修复：`main.py` 启动时装配注册表挂 app.state（app/main.py:128-134）。
2. **离线配置不生效**：`knowledge/agent_tools.py` 模块级 `FastEmbedProvider()` 无视
   `EMBEDDING_ENABLED=false`，导入即加载向量模型。修复：惰性构造 + 统一为
   `embeddings.embedding_provider_from_settings`（三处调用点收敛为一）。

**可读性修复**
3. 删除死文件 `web/src/features/documents/DocumentWorkspace.tsx`（无引用、直连 fetch 的旧实现）。
4. 删除死代码：CSS `.task-badge`/`.review-task-source`、`zhCN.roleShort`、
   `global-setup.ts` 遮蔽用的模块级端口常量。
5. `quality/_get_document` → 重命名 `get_contract_document` 公开导出（消除跨模块私有导入）。
6. `quality/router.py` 函数内重复导入（同名遮蔽）移除；`compare.py` 加模块 docstring
   说明其与 `comparison.py` 的分工。
7. `core/config.py` 注释与实现对齐（embedding 关闭时无 degraded 字段，如实描述）。
8. 脚本可移植性：`scripts/*.py` 补 sys.path 引导，`python scripts/xxx.py` 直接可跑
   （此前必须 PYTHONPATH=. ；README 已相应简化）。

**未改动（记入已知事项）**：`App.tsx` 单组件 ~390 行（拆分会动全局状态流，交付前不动）；
`quality/check.py` 与 `judge.py` 行为等价（保留，避免行为变更）；E2E spec 的
skip 守卫不一致（低影响）。

## 三、验证证据（交付基线）

| 项 | 结果 |
|---|---|
| 后端 pytest | **227 passed, 1 skipped**（含新增 admin_users 7 / ingestion_queue 3 / draft_tool 5 / identity_roles 2） |
| 前端 vitest | **40 passed**（新增对比持久化 3、起草按钮 1、DocumentHub 草稿回填 2） |
| E2E | **11 passed**（5 spec：critical-flow、promotion-quality ×5、review-workspace、three-roles ×3、comparison），两次连续干净运行 |
| tsc | 干净 |
| ruff | `app tests scripts` 0 错误 |
| 浏览器实测 | 三角色登录/能力显隐、对比持久化、PDF 触发、起草回填（F 项发现并修复 1 个 bug，见第五节） |
| 打包 | `dist/doc-agent-delivery-20260911.zip`（220 文件 0.5MB，抽查关键文件在位、无 .env/.db/缓存泄漏） |
| 提交 | `65eea72`（本地分支 feature/doc-agent-foundation，未推送） |

## 四、给下一位接手者（重要约定）

1. **启动必须同时跑后端与 worker**：`uv run python run_dev.py` 会一起拉起；
   只跑 uvicorn 时上传不会自动索引（任务停在排队中，Job 面板可见）。
2. **新增质量工具**要同步补 `prompts.py` 的 `CAPABILITY_PROMPTS` ——
   `tests/unit/test_audit_prompt.py` 有反死代码回归测试会拦。
3. **改系统提示词**记得递增 `PROMPT_VERSION`。
4. **删/改状态机**：`app/reviews/workflow.py` 是唯一权威，前端 `ReviewPanel.NEXT_STATES`
   只是子集镜像。
5. 集成测试建库时 FTS 虚拟表需手动创建（`CREATE VIRTUAL TABLE knowledge_chunks_fts ...`）。

## 五、浏览器实测补记（三账号，隔离端口 8031/5211，未动用户开发库）

| 项 | 结果 |
|---|---|
| A 管理员「用户与角色」 | PASS：三账号列表 + 角色下拉 + 三角色能力说明 + 「（当前账号）」标记 |
| B 上级侧栏 | PASS：有「知识库治理」、无「管理」；直入 #management 显示优雅拒绝页 |
| C 版本对比 | PASS：「本地启发式 · 未接入模型」徽章如实标注，9 处变更卡片 |
| D 对比持久化 | PASS：正文↔对比切换后结果保留；切换版本 B 后清空 |
| E PDF 导出 | PASS：`window.print` 触发恰好 1 次 |
| F 起草回填 | **发现并修复 bug**：提示「已将 Agent 草稿填入编辑器」被 `updateDraft` 同批次清空（`DocumentHub.tsx` 调用顺序）。修复后补 2 个单测（`DocumentHub.test.tsx`）。编辑器回填与按钮行为实测正常 |
| G 控制台 | 无意外错误（仅 favicon 404，无害） |

E2E 全量：**11 passed / 0 failed**（含 three-roles ×3、comparison ×1 两组新 spec；
两次连续干净运行验证稳定）。

## 六、多角色演进（用户确认：上线时将变为「一人兼多角色」）

已按「写方案 + 预留接缝」落实：

- **接缝收敛**（本轮已做）：全局角色判断全部走 `app/identity/roles.py` 与
  `web/src/app/roles.ts` 两个入口，业务代码零直接 `role ==` 比较（消息 role 除外）；
  管理员与 reviewer 并存时的入口去重已处理。
- **迁移蓝图**：`docs/multi-role-migration.md` —— user_roles 表、双读过渡、
  接口 `roles: list`、JWT 升级、前端多选，含风险表与验收清单。下一轮按该文档实施。
