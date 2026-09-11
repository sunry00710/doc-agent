import { expect, test } from '@playwright/test'

type Fixture = {
  baseURL: string
  password: string
  admin: string
}

const fixture = JSON.parse(
  process.env.DOC_AGENT_ISOLATED_E2E ?? '{}',
) as Fixture

test.skip(!fixture.baseURL, 'Isolated E2E setup is unavailable')

test.use({ baseURL: fixture.baseURL })

test.describe('critical document workflow', () => {
  test('login, restore workspace state, and reach knowledge search', async ({ page }) => {
    await page.goto('/')
    await page.locator('input[autocomplete="username"]').fill(fixture.admin)
    await page.locator('input[autocomplete="current-password"]').fill(fixture.password)
    await page.getByRole('button', { name: '登录' }).click()
    await expect(page.getByText('Doc Agent').first()).toBeVisible()

    await page.getByRole('button', { name: '文档', exact: true }).click()
    await expect(page.locator('.document-list > h2')).toBeVisible()
    const documentButton = page.locator('.document-list button').first()
    await expect(documentButton).toBeVisible()
    await documentButton.click()
    const versionButton = page.locator('.version-list button').first()
    await expect(versionButton).toBeVisible()
    await versionButton.click()

    await page.getByRole('button', { name: '工作台' }).click()
    await expect(page.getByText('已绑定上下文')).toBeVisible()
    await page.locator('#agent-message').fill('检查当前文档')
    await page.getByRole('button', { name: '发送' }).click()
    await expect(page.locator('.messages')).toContainText('Agent')
    await page.reload()
    await expect(page.getByText('已绑定上下文')).toBeVisible()
    await expect(page.locator('.messages')).toContainText('检查当前文档')

    await page.getByRole('button', { name: '知识库' }).click()
    await expect(page.getByRole('heading', { name: '知识库', exact: true })).toBeVisible()
    await page.getByLabel('知识库搜索').fill('E2E')
    await page.getByRole('button', { name: '搜索' }).click()
    await expect(page.locator('.search-results, .muted').first()).toBeVisible()
  })
})
