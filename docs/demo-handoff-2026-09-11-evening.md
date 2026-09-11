# Doc Agent 交接文档（2026-09-11 傍晚 — 交给下一个 AI）

> 前序文档：`docs/demo-handoff-2026-09-11.md`（上午验收）、`docs/demo-handoff-2026-09-11-final.md`（下午改造）。
> **本文件是当前状态快照 + 未完成任务清单**，接手请从这里开始。

## 〇、工作区状态（最重要）

```
项目根: D:\workspace1\doc-agent-worktrees\foundation
分支: feature/doc-agent-foundation（仅本地，未 push）
最新提交: 339f867（语义对比）← 1d5821a（审计 system prompt）← ef1ae09（FilePicker）← fcf76a3（主提交）
工作区: 干净（截至 2026-09-11 夜，接手方验证并提交后）
```

- **服务当前在运行**：后端 127.0.0.1:8000、前端 127.0.0.1:5173、登录 `demo / DemoPass-2026!`
- 重启命令见 `docs/demo-handoff-2026-09-11.md` 第一节
- **历史提交链**：上午验收 → `fcf76a3`（77 文件，双 Provider + 上下文模型）→ `ef1ae09`（FilePicker + 布局修复）→ `1d5821a`（审计 prompt）→ `339f867`（语义对比三引擎）
- **下一步工作见第九节「接手方验证记录」的 9.4 遗留表**

## 一、测试基线（当前全绿）

| 套件 | 命令 | 结果 |
|---|---|---|
| 后端 | `uv run pytest tests/integration tests/unit -q` | **208 passed, 1 skipped** |
| 前端 | `npm --prefix web test -- --run` | **34 passed** |
| E2E | `npm --prefix web run test:e2e` | **7 passed**（自起隔离环境，独立端口） |
| 类型 | `cd web && npx tsc --noEmit` | 干净 |

## 二、用户本次提出的 6 个问题（已取证，答案在此）

### Q1. 需要三种账户：管理员 / 上级 / 下级（员工）

**现状**：只有全局 `Role`：`user` / `reviewer` / `admin`（`app/identity/models.py:14-17`）
**已有的项目级权限**（`app/projects/permissions.py` ROLE_ACTIONS）：

| 项目角色 | 权限 |
|---|---|
| contributor | view, edit, comment, submit |
| reviewer | + review |
| owner | 全部 |

**用户要的映射**建议：
- 管理员 = 全局 `admin`
- 上级 = `reviewer` + 项目 `reviewer`/`owner`（可评审、可批准晋升）
- 下级（员工）= `user` + 项目 `contributor`（提交、编辑、评论，不可批准）

**待办**：①确认映射是否符合用户预期 ②UI 上明确展示当前角色能做什么 ③可能需要在管理页加"用户管理"（现在只有项目成员管理，`ManagementWorkspace.tsx`）④补一个创建 reviewer/admin 账号的脚本或界面（现只有 `scripts/bootstrap_admin.py`）

### Q2. 页面级完整功能测试

**已完成**：验收 1-9 项（评审闭环、晋升、索引、检索、撤销、鉴权）+ E2E 7 项
**待办**：按"管理员/上级/下级"三种账号各跑一遍全流程，确认权限隔离符合 Q1 的预期。

### Q3. 拖拽支持什么格式？

**实测答案**：`.md` 和 `.txt`，**仅 UTF-8 编码**，最大 10MB
- 校验点：`app/documents/storage.py:64-74`（后缀白名单 + 大小 + UTF-8 解码）
- **不支持**：PDF、Word（.docx）、Excel、图片
- 若要支持更多格式，需在后端加解析器（如 pypdf / python-docx），并在 `_validate_and_normalize` 扩展白名单

### Q4. 能否直接在 Agent 里起草文件？

**不能**。当前 Agent 只能：检索知识库、检查/改写已有正文、对比版本。
**没有"从头写一篇新文档"的工具**。用户想"直接起草"需要：
- 后端：新增 `draft_document` 工具（生成正文 → 写入新 Document；需定义是存入项目文档还是仅返回草稿文本）
- 前端：工作台加"新建草稿"入口，或用 Agent 输出 + 现有「保存为新版本」按钮落地
**建议实现**：Agent 生成 → 前端显示 → 用户点"保存为草稿"调用现有 `createDocument` + `uploadVersion`（复用现有链路，改动小）

### Q5. 能识别什么文件？

同 Q3：仅 `.md` / `.txt` 的**文本内容**。所谓"识别"就是按 UTF-8 读文本——**没有 OCR、没有 PDF 解析、没有 docx 解析**。

### Q6. 导出 PDF？

**完全没有导出功能**（grep 确认 `web/src` 无任何 download/export）。实现建议：
- 前端：`react-to-print`（最简单）或 `window.print()` + @media print 样式
- 后端：weasyprint/pandoc（重，且要考虑集团内网依赖）
- **建议**：先用前端打印方案（零后端依赖，半天内可完成）

### Q7. 语义对比用 AI 吗？提示词编排如何？

**答：语义对比完全不用 AI。**

| 组件 | 用 AI？ | 证据 |
|---|---|---|
| **版本对比（含"语义对比"）** | ❌ **纯 difflib 算法** | `app/quality/router.py:83-91` `difflib.SequenceMatcher` 逐行 diff |
| check/rewrite/judge | ❌ 纯本地校验 | `quality/tools.py` → `normalize_findings` 比对切片 |
| Agent 对话 | ✅ 走 Provider | `AgentRunner.run` → `provider.complete()` |
| 知识库检索 | ⚠️ 半 AI | FastEmbed 向量 + SQLite FTS，无 LLM |

**重要发现（两处）**：
1. **"语义对比"是误称**——实际是逐行文本 diff。`comparison_type=semantic/requirements/standards`
   三个选项**行为完全相同**（`router.py:81` 只用于摘要文案）。
2. **`app/quality/prompts.py` 是死代码**——CHECK/REWRITE/COMPARE/REVIEW/JUDGE
   五个 prompt 常量**无任何引用**（后端审计独立确认）。真实流程中模型自发决定工具调用，
   **没有 system prompt 注入质量约束**。后果：接真实模型后，模型不知道
   "evidence 必须是原文切片"等规则，只能靠工具执行失败兜底。

**待办（接真实模型前最该做）**：
- 把 `prompts.py` 激活为 system prompt：`AgentRunner.run`（`loop.py:80`）目前只发 user 消息，
  需在 messages 前加 `ModelMessage(role="system", content=...)`
- ✅ **已完成（2026-09-11 夜间）**，实现与提示词全文见第七节
- 提示词内容参考：本产品 PRD 的五场景要求（证据绑定、逻辑错位标记、人工复核降级）
  + 审计署公文写作规范；GitHub 上 `audit-writing` 类 skill 大概率无高质量现成件，
  建议自行编写
- 可搜关键词：`claude skill legal writing` / `audit report prompt`

## 三、用户指出的两个 UI 布局问题（已修复，2026-09-11 晚）

### 问题 A：工作台"空旷" ✅ 已修

**根因**：`.conversation` 声明 3 行网格（`auto 1fr auto`），实际有 5 个子元素 →
隐式行分配错乱产生大空白。
**修复**：`grid-template-rows: auto auto auto minmax(0, 1fr) auto; align-content: start`
+ `.conversation-compact` 用 4 行变体（`styles.css`）。

### 问题 B：目标文档选择框"有点挤" ✅ 已修

**根因**：`width: 100%` 在宽屏被拉成大块白条。
**修复**：`max-width: 420px` + 间距调整。

### 附带修复：来源芯片变椭圆 ✅ 已修

**根因**：全局 `label { display: grid }` 命中新加的 `<label class="source-chip">`。
**修复**：`.source-chip` 显式 `display: inline-flex; align-self: center; width: auto`。

## 四、仍未接线（下午审计发现，优先级排序）

| 优先 | 项 | 位置 | 说明 |
|---|---|---|---|
| P1 | Job 队列无生产端 | `app/jobs/service.py` enqueue 无调用者 | JobStatus 面板恒空；实际入库走同步 |
| P1 | 评审乐观锁漏用 | `app/reviews/service.py:140+` | request_changes/add_comment 未用条件 UPDATE |
| P2 | 契约 standard_ids 无消费 | `app/quality/contracts.py` | 落库不参与质量门判定 |
| P2 | `AgentContext.project_id` 存而不读 | `app/agent/loop.py:31` | 与已修复的 document_version_id 同族 |
| P3 | CitationPanel 引用被子集替换 | `App.tsx` setCitations | 多轮对话引用链丢失 |
| P3 | 文档列表请求失败无错误态 | `App.tsx:119` | 失败显示为"没有文档" |

## 五、环境关键信息（接手必读）

- **模型**：`MODEL_PROVIDER=fake|self|internal`（默认 fake）。接真实模型需配 `SELF_AI_*` 或 `INTERNAL_API_*`，见 `.env.example`
- **向量模型**：`BAAI/bge-small-zh-v1.5`，下载须用 `HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1`
- **数据库**：SQLite + WAL 模式（`app/db/session.py`），本地库 `doc_agent.db`
- **跑测试**：见第一节表格；E2E 会自起隔离环境（不会污染开发库）
- **接口文档**：http://127.0.0.1:8000/docs（已配中文描述与标签）

## 六、本会话已完成（2026-09-11 全天汇总）

1. **验收**：评审流转闭环、双库检索、版本对比、权限拒绝全部实测通过
2. **模型接入**：双 Provider 装配（自用 AI + 集团内网预留），配置缺失启动报错
3. **语义检索修复**：发现并修复"从未生效"的 embedding 断链（0 向量 → 回填 136 块）
4. **上下文模型**：质量工具绑定真实版本正文（防伪造）、知识来源多选、工作台自足选文档、会话保持
5. **UI**：苹果风重构（材质层级）、动效修复、文件选择器苹果风化、文档列表滚动+筛选
6. **基础设施**：WAL、备份/恢复脚本、token 过期自动跳登录、端口配置生效
7. **提交**：`fcf76a3`（77 文件）已入库；UI FilePicker 改造**未提交**

---
**接手建议顺序**：读本文件 → 跑一次三套测试确认基线 → 修 UI 两处布局（第三节）→ 按用户优先级做 Q1（角色）或 Q4（起草）→ 其余见第四、二节。

---

## 七、夜间进展（2026-09-11 晚 · 第二次交接）

### 7.1 已完成：审计领域 system prompt 接线（= Q7 待办 1/2/3）

| 文件 | 改动 |
|---|---|
| `app/quality/prompts.py` | **重写**：`PROMPT_VERSION=quality-v2`；新增 `ROLE_PROMPT` / `HARD_RULES` / `AUDIT_WRITING_RULES` / `CAPABILITY_PROMPTS` / `BOUNDARY_PROMPT`；`build_system_prompt()` 组装出 `SYSTEM_PROMPT`。原 CHECK/REWRITE/COMPARE/REVIEW/JUDGE 五个常量全部并入 prompt —— **不再是死代码** |
| `app/agent/loop.py` | `AgentRunner(..., system_prompt=...)`；在 user 消息前注入 `ModelMessage(role="system", ...)`；新增 `_conversation_length()`，system 是固定开销、不占 `max_messages` 预算（否则 `max_messages=3` 这类边界测试会静默少跑一轮工具） |
| `app/agent/router.py` | `get_runner()` 传入 `SYSTEM_PROMPT`（真实 API 路径唯一入口） |
| `tests/unit/test_audit_prompt.py` | 新增 5 个测试：system 注入位置、无 prompt 时保持原样、不占消息预算、五个能力常量必须出现在 prompt（反死代码回归）、prompt 覆盖后端硬校验字段 |
| `tests/integration/test_chat.py` | 新增 1 个测试：`POST /api/chat` 的首条消息必须是审计 system prompt |

**提示词内容**（对齐后端真实校验，不是泛泛的“写好一点”）：

- 6 条硬约束：evidence 必须是正文精确切片且 offset 对齐；summary 计数自洽；`logical_mismatch` 强制 `human_review_required=true`；对比 change 必须双版本绑定；只建议不改稿；citation 必须可核验
- 8 条审计文书写作规范：证据可溯源、金额/日期/单位精确、责任主体明确、五层信息不越级（行为事实 < 主张 < 证据载明 < 评价推论 < 有权认定）、逻辑链条完整、结论与建议对应、不得编造法规文号金额、表述克制
- 边界与降级：不越权定性、证据不足即标记待确认、检索不到就直说

**参考来源（GitHub 检索结论）**：审计领域**没有**高质量现成 skill；最接近的是
[`katejianglaw/refine-legal-chinese`](https://github.com/katejianglaw/refine-legal-chinese)（中文法务写作 skill：SKILL.md + `references/` 分层加载、通用 guardrails、quality checklist、一票否决条件）。
本次结构参考其思路，规则内容按审计文书与后端真实校验重写；**未写入未经核验的法条编号**（prompt 里明确要求法规名称/条款号只能来自知识库或用户材料）。

**测试基线**：`uv run pytest tests/unit tests/integration tests/evaluation -q` → **192 passed, 1 skipped**（改动前 186，新增 6）。

**生效条件**：后端需重启（当前 127.0.0.1:8000 进程未开 `--reload`，改动不会热加载）。

### 7.2 待决策：「语义对比」是误称（**未动手，等确认**）

`app/quality/router.py:83-91` 实际是 `difflib.SequenceMatcher` 逐行 diff，`comparison_type` 只影响
摘要文案（`_COMPARISON_TYPE_LABELS`），semantic / requirements / standards 三个选项行为完全相同。

| 方案 | 工作量 | 效果 |
|---|---|---|
| A 诚实改名 | ~10 分钟 | UI 下拉与摘要改为「文本差异对比」，不再宣称语义能力；零风险，但演示卖点变弱 |
| B 真做语义对比 | 2–4 小时 | 接 provider 让模型识别「改写但语义等价」的段落，provider 不可用时回退 difflib；需新增输出 schema、成本/超时控制、前端展示调整 |

### 7.3 顺手发现（未处理）

- `ruff check app tests` 现存 3 个**改动前就有**的报错：`tests/integration/test_quality_bound_source.py` 里 `text` / `Session` / `Finding` 三个未使用导入。与本次改动无关，未擅自修改。

---

## 八、夜间进展 2：版本对比真语义化（2026-09-11 深夜）

### 8.1 三引擎设计（`app/quality/comparison.py`，新增）

「语义对比」不再是 `difflib` 换皮。对比结果里**如实回报**用的哪种引擎，前端必须显示：

| engine | 触发条件 | 说明 |
|---|---|---|
| `llm` | 配置了真实 provider（`MODEL_PROVIDER=self` / `internal`） | 模型做语义对比：识别「改写但语义等价」、口径变化、数据变化、结构调整、语气变化；返回 JSON，后端组装 |
| `heuristic` | `FakeProvider` 离线演示模式 | 本地启发式：段落级 diff + 相似度（≥0.55 判为语义等价改写）+ 数字差异判为数据变化。**不冒称模型能力** |
| `difflib` | provider 缺失 / 超时 / 返回非法 JSON | 回退逐行 diff，响应里 `degraded=true` + `degraded_reason` |

实现要点：

- 模型只产出 `category/summary/old_text/new_text/impact/semantic_equivalent`；**版本 ID 一律由后端绑定**，
  模型无法张冠李戴（`compare_documents()` 仍做二次校验）
- 输出解析容错：允许 ```json 围栏、跳过无 summary 条目、未知 category 归为 `modification`、
  `{"changes": []}` 归为「无变化」；解析失败 → 降级而不是 500
- 单条消息上限定为 30k 字符，正文按需截断并回报 `truncated=true`；模型输出上限 2048 tokens、45s 超时
- 新增类别：`semantic_rewrite` / `data_change` / `structure_change` / `tone_change` / `comment_response`
- `ModelProvider.offline` 标记（`FakeProvider` 演示模式为 True），用于区分「没模型」和「模型挂了」

接口变化（`POST /api/quality/comparisons` 响应新增字段，向后兼容）：

```
engine: "llm" | "heuristic" | "difflib"
degraded: bool           degraded_reason: str | null
truncated: bool          comparison_type: str
changes[].old_text / new_text / impact / semantic_equivalent
```

测试：`tests/unit/test_semantic_comparison.py`（13 例）+ `tests/integration/test_semantic_comparison_api.py`（3 例）；
全量 `tests/unit tests/integration tests/evaluation` → **210 passed, 1 skipped**。

---

## 九、接手方验证记录（2026-09-11 更晚 — 交接确认）

上一棒 AI 在语义对比改造完成后宕机。接手方已完成以下验证，确认该轮工作**完整可交付**：

### 9.1 验证证据

| 项 | 结果 |
|---|---|
| 后端全量 | **208 passed, 1 skipped**（含新增语义对比测试） |
| 前端 | **34 passed**（7 文件，含 ComparisonView.test.tsx） |
| tsc | 干净 |
| API 实测 | `POST /api/quality/comparisons` → `engine: "heuristic"`（正确识别 FakeProvider 离线） |
| UI 实测 | 浏览器完整跑通：引擎徽章「本地启发式 · 未接入模型」橙色显示、说明文字「不是模型能力」、9 处变更含语义等价标记与原文片段对照 |
| 遗留标记 | 无 TODO/FIXME 残留 |

### 9.2 该轮已提交内容（`1d5821a`）

审计写作 system prompt 注入：`prompts.py` 激活（六条硬规则 + 八条审计/法务写作规则 + 能力契约边界），
`AgentRunner` 支持 system_prompt 参数且不计入 max_messages。

### 9.3 尚未提交（本次验证后建议直接提交）

工作区 13 文件：`app/quality/comparison.py`（新）、router/schemas/provider 改造、
前端 ComparisonView + client + strings + styles、测试 3 个新文件、交接文档更新。

### 9.4 已知遗留（按优先级）

| 优先 | 项 | 位置 |
|---|---|---|
| P1 | 三角色（管理员/上级/下级）——见本文件 Q1，尚未实施 | 需求 |
| P1 | 页面级三账号全流程测试 | 需求 |
| P2 | 对比结果未持久化：`ComparisonView` 用组件 state，切 tab 即丢 | `ComparisonView.tsx` |
| P2 | E2E 未覆盖版本对比功能 | `web/e2e/` |
| P2 | `ruff check` 3 个改动前就有的未使用导入 | `tests/integration/test_quality_bound_source.py` |
| P3 | 其余见本文件第四、二节（Job 队列、导出 PDF、起草功能等） |
