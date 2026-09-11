# 多角色（一人兼多角色）迁移方案

> 背景（用户确认，2026-09-11）：三角色管理实际**上线时会变成多角色**——
> 一个人可同时持有多个全局角色（如某人既是上级又是管理员）。
> 本轮交付保持单角色实现，但已完成**接缝收敛**；本文件是下一轮的实施蓝本。
> 经用户确认，多角色改造**不在本次交付范围**，交付后单独立项。

## 一、现状与接缝（已就绪）

全局角色判断已全部收敛到两个入口，业务代码不再直接比较 `role`：

| 层 | 入口文件 | 函数 |
|---|---|---|
| 后端 | `app/identity/roles.py` | `has_role` / `has_any_role` / `is_admin` / `can_govern_knowledge` |
| 前端 | `web/src/app/roles.ts` | `hasRole` / `hasAnyRole` / `isAdmin` / `canGovernKnowledge` |

已改走的调用点（搜索 `Direct role comparison` 时应为 0）：

- 后端：`admin/router.py`（is_admin）、`knowledge/promotion_service.py` ×3 与
  `knowledge/router.py`（can_govern_knowledge）、`projects/service.py`（is_admin）、
  `knowledge/router.py` 的治理列表过滤。
- 前端：`app/App.tsx` 全部导航与页面守卫。
- **未纳入**：`identity/service.py` 的 JWT `role` claim（认证协议的一部分，见下文迁移）；
  项目级角色（contributor/reviewer/owner）属另一维度，不在此方案范围。

## 二、目标模型

```
users (不变)          user_roles (新表)
+--------+            +------------------+
| id     |<---------->| user_id (FK)     |
| ...    |            | role (枚举)       |  ← 复合主键 (user_id, role)
+--------+            +------------------+
```

- `users.role` 单列**保留一个发布周期**（过渡期双读），随后删除。
- 约束：至少有 0 个角色的用户是合法状态（等于当前的普通用户）；
  「最后一个管理员」保护改为对 `user_roles` 计数。
- 枚举沿用现有三值起步；未来加角色种类只加枚举值。

## 三、迁移步骤（建议顺序，每步独立可回滚）

1. **建表 + 回填**（一个 alembic 迁移）：
   `user_roles`（user_id, role, created_at；PK(user_id, role)），
   回填 `INSERT INTO user_roles SELECT id, role FROM users`。
   **此步不动读取路径**（双写开始前先只回填）。
2. **后端读写切换**（不改接口形状）：
   - `User.roles` relationship；`User.role` 改为 property，返回角色集合中的
     「最高权」值（admin > reviewer > user）——保证所有旧读取点行为不变。
   - `app/identity/roles.py` 的实现改为集合判定（`has_any_role(u, *rs)` →
     `bool(set(u.roles) & set(rs))`）。**调用点一行不改**。
   - 写路径：`scripts/create_user.py`、`admin/router.py`、`seed_roles.py` 改操作 `user_roles`。
3. **接口升级**：`UserRead.role: Role` → 新增 `roles: list[Role]`，`role` 保留为
   兼容字段（值 = 最高权角色）；`PATCH /api/admin/users/{id}` 接受
   `roles: list[Role] | None`（整体替换语义），`role` 参数保留为「设置为单角色」的糖。
   前端 `User` 类型加 `roles` 字段。
4. **JWT 升级**：token claim `role: str` → `roles: list[str]`。
   校验改为「token 的角色集合是当前用户角色集合的子集」（角色被收回即失效）。
   **发布注意**：旧 token 无 `roles` → 一律 401 要求重登（有效期内一次性影响，可接受）。
5. **前端切换**：`roles.ts` 改读 `user.roles`；管理页「用户与角色」列由下拉改为
   多选（checkbox 组或标签+编辑弹层）；侧栏守卫逻辑不变。
6. **收尾**：删 `users.role` 列（再等一个发布周期）；`UserRead.role` 兼容字段可删。

## 四、风险与注意

| 风险 | 缓解 |
|---|---|
| 「最后管理员」判定窗口 | 迁移第 2 步起，降级检查改对 `user_roles` 计数；`update_user` 已有该逻辑，替换数据源即可 |
| 授权语义变化：单角色时代「角色即权限」，多角色后要明确是**并集**还是**任一满足** | 方案取并集（任一角色提供该权限）；`can_govern_knowledge` 等 helper 天然支持 |
| `is_admin` 大量用于「显示管理入口」 | 多角色下 admin 与 reviewer 并存时入口去重（本轮已修：`!isAdmin(user) && canGovernKnowledge(user)` 条件） |
| 旧客户端调用 `PATCH role` | 兼容字段保留，语义为「整体替换为单角色」，文档标注 deprecated |
| 审计要求「谁在什么角色下做的操作」 | token 中加入 `active_role`（可选，第四步之后单独立项）；当前记录 actor id 已满足最小审计 |

## 五、验收清单（迁移完成时）

- [ ] `grep -rn "\.role ==\|\.role !=" app/ web/src/`（排除测试与 roles.py/roles.ts 本体）为 0
- [ ] `app/identity/roles.py` 与 `web/src/app/roles.ts` 是唯一角色判断实现
- [ ] 同人多角色 e2e：admin+reviewer 用户看到管理入口且不重复渲染治理按钮
- [ ] 迁移脚本对既有库幂等（重复执行无副作用）
- [ ] 旧 token 在 JWT 升级后全部失效并有清晰重登提示
