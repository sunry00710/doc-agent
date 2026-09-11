import { expect, test, type Page } from '@playwright/test'

const fixture = JSON.parse(process.env.DOC_AGENT_ISOLATED_E2E ?? '{}') as {
  baseURL: string
  password: string
  author: string
  unconfirmedTitle: string
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

async function openComparison(page: Page) {
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name: '文档', exact: true }).click()
  await page.getByRole('button', { name: fixture.unconfirmedTitle, exact: true }).click()
  // seed 中该文档有两个版本，版本列表加载后点开对比页
  await page.locator('.version-list button').first().click()
  await page.getByRole('tab', { name: '版本对比' }).click()
}

test.describe('version comparison', () => {
  test('compares two versions, reports the engine honestly, and survives tab switches', async ({ page }) => {
    await login(page, fixture.author)
    await openComparison(page)

    // 默认选中最早与最新版本；离线演示模式必须如实标注引擎
    await page.getByRole('button', { name: '开始对比' }).click()
    await expect(page.locator('.engine-badge')).toBeVisible()
    await expect(page.locator('.comparison-headline')).toContainText('共发现')
    await expect(page.locator('.comparison-engine-note')).not.toBeEmpty()
    // 已启用真实 provider 时显示模型引擎，否则必须是如实的离线/降级标注
    const badge = await page.locator('.engine-badge').textContent()
    expect(badge).toMatch(/模型|启发式|逐行差异/)

    const changes = page.locator('.comparison-change')
    await expect(changes.first()).toBeVisible()
    // seed 的第二版补写了一段整改内容，对比必须发现变化
    await expect(page.locator('.comparison-changes')).not.toBeEmpty()
    await expect(page.locator('.comparison-result')).toContainText('补充')

    // 切走再回来：结果必须从会话存储恢复，而不是消失
    await page.getByRole('tab', { name: '正文' }).click()
    await expect(page.locator('.comparison-result')).toHaveCount(0)
    await page.getByRole('tab', { name: '版本对比' }).click()
    await expect(page.locator('.comparison-result')).toBeVisible()
    await expect(page.locator('.comparison-result')).toContainText('补充')

    // 切换所选版本后旧结果应被清空（避免显示与选择不符的空变更列表）
    await page.getByLabel('版本 B').selectOption({ index: 0 })
    await expect(page.locator('.comparison-result')).toHaveCount(0)
  })
})
