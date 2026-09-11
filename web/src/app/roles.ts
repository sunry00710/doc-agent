import type { User } from '../api/client'

// 全局角色的统一判断入口（多角色演进接缝）。
// 当前是单角色；「一人兼多角色」上线后只改这里（与后端 app/identity/roles.py 对应），
// 业务代码禁止直接比较 user.role === '...'（见 docs/multi-role-migration.md）。

export function hasRole(user: User, role: User['role']): boolean {
  return user.role === role
}

export function hasAnyRole(user: User, roles: User['role'][]): boolean {
  return roles.includes(user.role)
}

export function isAdmin(user: User): boolean {
  return hasRole(user, 'admin')
}

export function canGovernKnowledge(user: User): boolean {
  return hasAnyRole(user, ['reviewer', 'admin'])
}
