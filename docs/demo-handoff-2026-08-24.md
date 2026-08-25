# Doc Agent Demo 交接文档

> 交接日期：2026-08-24
> 分支：`feature/doc-agent-foundation`（仅本地，未 push、未 merge）
> HEAD：`1839be2`
> 测试基线：后端 158 passed / 1 skipped，前端 10 passed，生产构建通过，Ruff 全绿

## 一、本轮新增提交（自 7f6bb93 之后）

| 提交 | 内容 |
|---|---|
| `9471f90` | Task 15：Obsidian 安全导入命令 + 公开审计评估基线（Recall@6 / 引文正确率 / 重复发现率 / 对比覆盖率） |
| `454625c` | 清理评估目录误入的字节码 |
| `64282e7` | 新增 .gitignore（缓存/本地库/构建产物/截图） |
| `dd192d8` | Task 16：run_dev 启动器、Playwright E2E 骨架、失败恢复测试 |
| `232c4b5` | 后端：知识空间四级分级（个人/项目/共享/规范）、个人库自助创建与收录 API、Agent `search_knowledge` 检索工具、chat 的 knowledge_space_ids 真实授权（原 403）、FTS 标题入索引、契约模拟接口、演示数据脚本 |
| `1839be2` | 前端：全功能接线（评审流转/晋升治理/文档导入）、契约要求编辑器+模拟主管评审、全站中文化、暖色调主题、长文阅读布局（修复工作区被挤入右栏的网格错位）、版本显示《标题》vN 化 |

## 二、功能验证状态

### ✅ 已验证可用（真实浏览器端到端跑通）

- **认证与权限**：登录/角色（user/reviewer/admin）、项目成员权限（贡献者/评审员/所有者）
- **文档管理**：新建文档+上传 v1、上传新版本（v2/v3…）、不可变版本查看（SHA256 绑定）、正文逐字符保真
- **评审全链路**：发起评审 → 提交 → 自任评审员 → 审核中 → 选区锚定评论（真实字符偏移+正文高亮）→ 请求修改/批准 → 重新提交 → 转入晋升 → 确认已索引 → 归档；乐观锁冲突（409）保留草稿提示
- **写作契约**：requirements 编辑器（增删+必须开关）、保存修订版、模拟主管评审（逐条 已满足/未满足 + 主管关注点 + 作者待办）、评审员确认
- **知识库**：四级空间分级展示与授权过滤、个人库自助创建/版本收录（无门禁）、晋升治理全流程（申请→质量门→批准→激活索引→撤销）、中英文关键词检索（标题入索引后按章节标题可命中）
- **Agent 工作台**：上下文绑定（project_id + document_version_id，横幅显示）、检索意图识别 → search_knowledge 工具调用 → 引文回复（0 命中自动降级为二字核心词重试）、变更类操作二次确认（中英文关键词）、工具轨迹展示
- **版本对比**：中文化界面、单版本引导、A/B 默认选中、真实数据对比（政府公告 44670/49624/39006 字精确一致）
- **任务**：失败任务列表+重试

### ⚠️ 演示级（功能可用但为离线实现）

- **Agent 回复**：FakeProvider 离线演示（检索类问题基于真实检索结果生成引文回复；非检索问题返回固定文案）。接真实 LLM：`app/providers/openai_compatible.py` 已就绪，配置 `MODEL_*` 环境变量即可
- **语义（dense）检索**：fastembed 模型未缓存时自动降级为关键词检索（UI 无感）。部署时预下载 `BAAI/bge-small-zh-v1.5`（约 90MB，下载一次永久离线可用）
- **版本对比结果**：字数级摘要（"版本 A 共 X 字，版本 B 共 Y 字"），非红绿 diff 可视化
- **契约评估**：子串匹配（要求文本出现在正文即满足），非 AI 判定；接真实模型后可升级为含 unknown 的语义判定

### ❌ 已知缺陷（未修，接手人优先级参考）

1. **晋升撤销后无法重新申请**：`request_promotion` 幂等检查返回旧 revoked 记录，需放开 revoked 状态的重申请（`app/knowledge/promotion_service.py`）
2. **刷新丢会话状态**：选中文档/版本、Agent 对话存于 React state，刷新即失。建议将选中版本写入 URL hash 或 sessionStorage
3. **Playwright E2E 仅骨架**：`web/e2e/critical-flow.spec.ts` 只有导航，完整业务链（导入→Agent→引文→评审→晋升→检索）未写。手动验证路径见下文演示脚本
4. **检索结果不可点击跳转**：引文/搜索命中仅展示，无跳转源文档（CitationPanel 仍是 window.alert）
5. **chat 的 knowledge_space_ids 前端未暴露**：API 已可用（含授权校验+检索范围收窄），前端无选择器

## 三、快速演示脚本（5 分钟）

启动（两个终端）：

```bash
cd D:/workspace1/doc-agent-worktrees/foundation
.venv/Scripts/python.exe run_dev.py --no-worker        # 后端 127.0.0.1:8000
npm --prefix web run dev -- --host 127.0.0.1 --port 5173  # 前端
```

账号：`demo / DemoPass-2026!`（仅本地演示）

推荐叙事线（体现"AI 质量门"产品定位）：

1. **写作前对齐**：文档页选《2026 年上半年审计整改报告》v1 → 写作契约标签 → 展示预置契约（6 条要求）→ 点"运行模拟主管评审"→ 5/6 满足、"整改责任清单"未满足（红色）+ 主管关注点
2. **知识检索**：知识库页搜"差旅"/"印章"/"比价"→ 多来源命中（8 份制度文档）；工作台输入"根据知识库检索一下差旅补助标准"→ 工具轨迹两次检索（降级重试）→ 引文回复
3. **治理闭环**：文档页《采购比价整改方案》v2 → 评审标签（当前停在"审核中"，可现场演示请求修改→重新提交→批准）→ 知识库晋升申请→批准→激活索引→回到评审确认已索引→归档
4. **真实数据对比**：《中央部门单位预算执行审计结果公告（2023-2025年度）》v1/v2/v3（审计署真实公告，规范化导入）→ 版本对比标签

## 四、数据资产位置

| 资产 | 位置 | 说明 |
|---|---|---|
| 政府公告原文（爬取） | `D:\Obsidian\Workspace1\10-历史报告-clean\` | 2023/2024/2025 年度审计结果，已规范化导入 demo |
| 历史验证记录 | `D:\Obsidian\Workspace1\30-验证记录\` | 含 2024 vs 2025 的 AI 对比记录（deepseek，含 token 成本） |
| 评估问题集/标注 | `tests/fixtures/evaluation/` | 公开审计语料的 golden set |
| 提示词资产 | `D:\Obsidian\agent\prompts\` | compare/judge/review/rewrite 四套已验证提示词 |
| 本地演示数据库 | `doc_agent.db`（已 gitignore） | 含演示项目、8 份制度文档、政府公告三版本、部分评审流转状态 |

注意：方向转向后，黑曜石资产**不废弃**——爬取语料、评估基线、提示词均为可复用资产，可平移至 Workbuddy 方向做验证。

## 五、后续路线建议（按优先级）

1. **P0 修缺陷**：晋升 revoked 重申请（演示阻断项）、刷新状态持久化
2. **P1 接真实模型**：OpenAI-compatible provider 配置真实 LLM → 契约评估/对比/检查五工具升级为 AI 判定；预下载 embedding 模型启用语义检索
3. **P1 完整 E2E**：补 Playwright 业务链测试（规格 §13 要求）
4. **P2 体验**：对比 diff 可视化（红绿高亮）、引文跳转源文档、检索范围选择器
5. **P2 契约增强**：required sections / 数据源 / 禁用措辞 / 截止日期字段（需 Alembic 迁移）
6. **P3 生产化**：PostgreSQL、对象存储、Nginx/HTTPS、密钥管理（当前为 SQLite+本地文件+开发 JWT，staging 水平）

**架构定位建议**：本 demo 的文档质量/知识库分级/评审流/Agent 工具链均为通用能力，可直接作为 Workbuddy 方向的技术底座演进；规格文档（`docs/superpowers/specs/2026-08-18-doc-agent-design.md`）中的检索优先级、实时协作（Tiptap+Yjs）等设计保留为演进路线。

## 六、重要注意事项

- **不要 push / merge**：分支仅本地，`doc_agent.db`、`storage/`、`web/.edge-profile/`、截图均为本地工件已 gitignore，不要删除
- **演示账号密码已暴露于本地会话**：共享环境前必须更换
- **后端 8000 / 前端 5173 端口**可能被本机残留进程占用：`netstat -ano | findstr :8000` 后 Stop-Process
- 规格与实施计划：`docs/superpowers/specs/2026-08-18-doc-agent-design.md`、`docs/superpowers/plans/2026-08-18-doc-agent-foundation.md`
