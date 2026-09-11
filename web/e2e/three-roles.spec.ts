import { expect, test, type Page } from '@playwright/test'

const fixture = JSON.parse(process.env.DOC_AGENT_ISOLATED_E2E ?? '{}') as {
  baseURL: string
  password: string
  author: string
  reviewer: string
  admin: string
}

test.skip(!fixture.baseURL, 'Isolated E2E setup is unavailable')

test.use({ baseURL: fixture.baseURL })

async function login(page: Page, username: string) {
  await page.goto('/')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(fixture.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByText('Doc Agent').first()).toBeVisible()
}

function nav(page: Page, name: string) {
  return page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name, exact: true })
}

test.describe('role separation across the three account types', () => {
  test('admin manages users and sees the role guide', async ({ page }) => {
    await login(page, fixture.admin)
    await expect(page.locator('.account')).toContainText('管理员')

    await nav(page, '管理').click()
    await expect(page.getByRole('tab', { name: '用户与角色' })).toBeVisible()
    await page.getByRole('tab', { name: '用户与角色' }).click()

    await expect(page.getByText('全部用户')).toBeVisible()
    // 三角色能力说明必须出现，且三种账号都在列表里
    await expect(page.getByText('管理用户与项目成员、评审、知识库治理')).toBeVisible()
    await expect(page.getByText('审核与批准下属提交、发起晋升治理')).toBeVisible()
    await expect(page.getByText('编辑提交、评论、向知识库投稿')).toBeVisible()
    await expect(page.getByRole('cell', { name: fixture.admin })).toBeVisible()
    await expect(page.getByRole('cell', { name: fixture.reviewer })).toBeVisible()
    await expect(page.getByRole('cell', { name: fixture.author })).toBeVisible()
    // 当前账号自己不能停用
    await expect(page.getByRole('row', { name: new RegExp(fixture.admin) }).getByText('（当前账号）')).toBeVisible()
  })

  test('employee (author) cannot manage users or approve', async ({ page }) => {
    await login(page, fixture.author)
    await expect(page.locator('.account')).toContainText('员工（下级）')

    // 无管理入口
    await expect(nav(page, '管理')).toHaveCount(0)
    // 管理 API 直连被拒
    const denied = await page.evaluate(async () => {
      const token = sessionStorage.getItem('doc-agent-token')
      const response = await fetch('/api/admin/users', { headers: { Authorization: `Bearer ${token}` } })
      return response.status
    })
    expect(denied).toBe(403)

    // 文档页看不到批准动作
    await nav(page, '文档').click()
    await page.locator('.document-list button').first().click()
    await expect(page.getByRole('textbox', { name: '正文草稿' })).toBeVisible()
    await expect(page.getByRole('button', { name: '批准', exact: true })).toHaveCount(0)
    // 员工有编辑权：保存为新版本按钮存在
    await expect(page.getByRole('button', { name: '保存为新版本' })).toBeVisible()
  })

  test('supervisor (reviewer) can govern promotions but not manage users', async ({ page }) => {
    await login(page, fixture.reviewer)
    await expect(page.locator('.account')).toContainText('上级审核')

    // 上级没有「管理」导航（那是管理员专属），但有知识库治理入口（侧栏 + 知识库页内）
    await expect(nav(page, '管理')).toHaveCount(0)
    await nav(page, '知识库').click()
    await expect(nav(page, '知识库治理')).toBeVisible()
    await expect(page.getByRole('main').getByRole('button', { name: '知识库治理', exact: true })).toBeVisible()

    // 管理 API 直连同样被拒
    const denied = await page.evaluate(async () => {
      const token = sessionStorage.getItem('doc-agent-token')
      const response = await fetch('/api/admin/users', { headers: { Authorization: `Bearer ${token}` } })
      return response.status
    })
    expect(denied).toBe(403)
  })
})
