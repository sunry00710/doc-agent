import { expect, test, type Page } from '@playwright/test'

type Fixture = {
  baseURL: string
  password: string
  author: string
  reviewer: string
  admin: string
  mandatoryTitle: string
  optionalTitle: string
  unconfirmedTitle: string
  optionalNeedle: string
}

const fixture = JSON.parse(
  process.env.DOC_AGENT_ISOLATED_E2E ?? '{}',
) as Fixture

test.skip(!fixture.baseURL, 'Isolated E2E setup is unavailable')

test.use({ baseURL: fixture.baseURL })
test.describe.configure({ mode: 'serial' })

async function login(page: Page, username: string) {
  await page.goto('/')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(fixture.password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByText('Doc Agent').first()).toBeVisible()
}

async function selectVersion(page: Page, title: string) {
  await page.getByRole('button', { name: '文档', exact: true }).click()
  await page.getByRole('button', { name: title }).click()
  await page.locator('.version-list button').first().click()
}

async function requestPromotion(page: Page) {
  await page.getByRole('button', { name: '知识库' }).click()
  await page.getByRole('button', { name: /申请晋升/ }).click()
  const target = page.getByLabel('目标知识空间')
  await target.selectOption({ index: 1 })
  await page.getByRole('button', { name: '确认申请' }).click()
}

function promotionRow(page: Page, title: string) {
  return page.locator('.promotion-row').filter({ hasText: title })
}

test('author sees blocked and human-review promotion policies', async ({ page }) => {
  await login(page, fixture.author)
  await expect(page.getByText('普通用户')).toBeVisible()

  await selectVersion(page, fixture.mandatoryTitle)
  await requestPromotion(page)
  await expect(page.getByRole('alert')).toContainText('提交的数据无效')
  await page.getByRole('button', { name: '取消' }).click()
  await expect(promotionRow(page, fixture.mandatoryTitle)).toHaveCount(0)

  await selectVersion(page, fixture.optionalTitle)
  await requestPromotion(page)
  const optional = promotionRow(page, fixture.optionalTitle)
  await expect(optional).toContainText('等待评审')
  await expect(optional).toContainText('需人工复核')
  await expect(optional.getByRole('button', { name: '批准' })).toHaveCount(0)

  await selectVersion(page, fixture.unconfirmedTitle)
  await requestPromotion(page)
  const unconfirmed = promotionRow(page, fixture.unconfirmedTitle)
  await expect(unconfirmed).toContainText('等待评审')
  await expect(unconfirmed).toContainText('需人工复核')
})

test('reviewer approves optional promotion and verifies retrieval', async ({ page }) => {
  await login(page, fixture.reviewer)
  await expect(page.getByText('审核员')).toBeVisible()
  await page.getByRole('button', { name: '知识库' }).click()
  await expect(page.locator('.promotion-row').getByRole('button', { name: '批准' })).toHaveCount(0)
  await page.getByRole('button', { name: '知识库治理', exact: true }).click()
  const optional = promotionRow(page, fixture.optionalTitle)
  await optional.getByRole('button', { name: '批准' }).click()
  await expect(optional).toContainText('已批准')
  await optional.getByRole('button', { name: '激活索引' }).click()
  await expect(optional).toContainText('已索引')

  await page.getByRole('button', { name: '返回知识库' }).click()
  await page.getByLabel('知识库搜索').fill(fixture.optionalNeedle)
  await page.getByRole('button', { name: '搜索' }).click()
  const hit = page.locator('.search-hit').filter({
    hasText: fixture.optionalTitle,
  })
  await expect(hit).toHaveCount(1)
  await hit.click()
  await expect(page.getByText(fixture.optionalNeedle)).toBeVisible()
})

test('admin approves unconfirmed promotion', async ({ page }, testInfo) => {
  await login(page, fixture.admin)
  await expect(page.getByText('管理员')).toBeVisible()
  await page.getByRole('button', { name: '管理', exact: true }).click()
  await page.getByRole('button', { name: '知识库治理', exact: true }).click()
  const unconfirmed = promotionRow(page, fixture.unconfirmedTitle)
  await unconfirmed.getByRole('button', { name: '批准' }).click()
  await expect(unconfirmed).toContainText('已批准')
  await page.screenshot({ path: testInfo.outputPath('governance-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('governance-mobile.png'), fullPage: true })
})

test('reviewer confirms contract and activates approved promotion', async ({ page }) => {
  await login(page, fixture.reviewer)
  await selectVersion(page, fixture.unconfirmedTitle)
  await page.getByRole('tab', { name: '写作契约' }).click()
  await expect(page.getByRole('heading', { name: /待确认/ })).toBeVisible()
  await page.getByRole('button', { name: '确认当前修订' }).click()
  await expect(page.getByRole('heading', { name: /已确认/ })).toBeVisible()

  await page.getByRole('button', { name: '知识库' }).click()
  await page.getByRole('button', { name: '知识库治理', exact: true }).click()
  const unconfirmed = promotionRow(page, fixture.unconfirmedTitle)
  await unconfirmed.getByRole('button', { name: '激活索引' }).click()
  await expect(unconfirmed).toContainText('已索引')
})

test('revocation in governance removes the indexed source from search', async ({ page }) => {
  await login(page, fixture.reviewer)
  await page.getByRole('button', { name: '知识库', exact: true }).click()
  await page.getByRole('button', { name: '知识库治理', exact: true }).click()
  const optional = promotionRow(page, fixture.optionalTitle)
  await optional.getByRole('button', { name: '撤销', exact: true }).click()
  await expect(optional).toContainText('已撤销')
  await page.getByRole('button', { name: '返回知识库' }).click()
  await page.getByLabel('知识库搜索').fill(fixture.optionalNeedle)
  const response = page.waitForResponse((response) => response.url().endsWith('/knowledge/search') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  expect((await response).ok()).toBe(true)
  await expect(page.locator('.search-hit').filter({ hasText: fixture.optionalTitle })).toHaveCount(0)
})
