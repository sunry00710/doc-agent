import { expect as baseExpect, test, type Page } from '@playwright/test'

// 提交/领取/批准等写操作与后台索引 worker 共用同一个 SQLite（单写者）。
// worker 正在建索引时，API 的写事务会排队等待（busy_timeout=15s），
// 因此本 spec 的断言窗口放宽到 15s，避免把「等待写锁」误判成功能失败。
const expect = baseExpect.configure({ timeout: 15_000 })

const fixture = JSON.parse(process.env.DOC_AGENT_ISOLATED_E2E ?? '{}') as {
  baseURL: string; author: string; reviewer: string; admin: string; password: string
}
test.use({ baseURL: fixture.baseURL })

async function login(page: Page, username: string) {
  await page.goto('/')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(fixture.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByText('Doc Agent').first()).toBeVisible()
}

async function navigate(page: Page, name: string) {
  await page.getByRole('navigation', { name: '主导航' }).getByRole('button', { name, exact: true }).click()
}

test('separates author drafts from assigned review tasks through a full revision cycle', async ({ browser }, testInfo) => {
  const authorContext = await browser.newContext({ baseURL: fixture.baseURL })
  const reviewerContext = await browser.newContext({ baseURL: fixture.baseURL })
  const adminContext = await browser.newContext({ baseURL: fixture.baseURL })
  try {
    const author = await authorContext.newPage()
    const reviewer = await reviewerContext.newPage()
    const admin = await adminContext.newPage()
    await login(author, fixture.author)
    await navigate(author, '文档')
    const title = '评审工作区分离验收'
    const source = '采购整改：补齐三家供应商报价，并归档采购材料。'
    const revised = `${source}\n责任人：项目经理；完成标准：报价材料归档并复核。`
    const createForm = author.getByRole('form', { name: '新建文档' })
    await createForm.getByLabel('标题').fill(title)
    await createForm.getByLabel('正文文件', { exact: true }).setInputFiles({ name: 'review.md', mimeType: 'text/markdown', buffer: Buffer.from(source) })
    await createForm.getByRole('button', { name: '创建并上传 v1' }).click()
    await expect(author.getByRole('textbox', { name: '正文草稿' })).toHaveValue(source)
    await expect(author.getByRole('tab', { name: '评审', exact: true })).toHaveCount(0)
    await author.getByRole('button', { name: '提交 v1 评审' }).click()
    await expect(author.getByRole('region', { name: '文档评审状态' })).toContainText('已提交')

    await login(reviewer, fixture.reviewer)
    await navigate(reviewer, '文档')
    await reviewer.getByRole('button', { name: title, exact: true }).click()
    await expect(reviewer.getByRole('textbox', { name: '正文草稿' })).toHaveValue(source)
    await reviewer.getByRole('textbox', { name: '正文草稿' }).fill('独立保存的未提交草稿')
    await navigate(reviewer, '待我评审')
    await reviewer.getByRole('tab', { name: /待领取/ }).click()
    await reviewer.getByRole('button', { name: new RegExp(title) }).click()
    await expect(reviewer.locator('.review-source')).toHaveText(source)
    await expect(reviewer.getByRole('textbox', { name: '正文草稿' })).toHaveCount(0)
    await expect(reviewer.getByRole('tablist', { name: '文档视图' })).toHaveCount(0)
    await reviewer.getByRole('button', { name: '领取评审任务' }).click()
    await reviewer.getByRole('button', { name: '开始评审' }).click()
    await expect(reviewer.getByRole('button', { name: '批准', exact: true })).toBeVisible()
    await reviewer.screenshot({ path: testInfo.outputPath('review-desktop.png'), fullPage: true })
    await reviewer.setViewportSize({ width: 390, height: 844 })
    await expect(reviewer.getByRole('button', { name: '批准', exact: true })).toBeVisible()
    expect(await reviewer.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await reviewer.screenshot({ path: testInfo.outputPath('review-mobile.png'), fullPage: true })
    await reviewer.setViewportSize({ width: 1440, height: 1000 })

    await login(admin, fixture.admin)
    await navigate(admin, '管理')
    await expect(admin.getByRole('cell', { name: '项目负责人', exact: true })).toBeVisible()
    await admin.screenshot({ path: testInfo.outputPath('management-desktop.png'), fullPage: true })
    await admin.setViewportSize({ width: 390, height: 844 })
    expect(await admin.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await admin.screenshot({ path: testInfo.outputPath('management-mobile.png'), fullPage: true })
    await admin.setViewportSize({ width: 1440, height: 1000 })
    await admin.getByRole('tab', { name: '我的后台任务' }).click()
    await expect(admin.getByText('暂无后台任务。')).toBeVisible()
    await navigate(admin, '待我评审')
    await expect(admin.getByRole('button', { name: new RegExp(title) })).toHaveCount(0)
    await navigate(admin, '文档')
    await admin.getByRole('button', { name: title, exact: true }).click()
    await expect(admin.getByRole('textbox', { name: '正文草稿' })).toHaveValue(source)
    await expect(admin.getByRole('button', { name: '批准', exact: true })).toHaveCount(0)

    await reviewer.getByRole('textbox', { name: '请求修改意见' }).fill('请明确责任人和完成标准。')
    await reviewer.getByRole('button', { name: '请求修改', exact: true }).click()
    await expect(reviewer.getByText('等待作者返修。')).toBeVisible()
    await navigate(reviewer, '文档')
    await expect(reviewer.getByRole('textbox', { name: '正文草稿' })).toHaveValue('独立保存的未提交草稿')

    await author.getByRole('button', { name: '刷新状态' }).click()
    await expect(author.getByRole('region', { name: '文档评审状态' })).toContainText('需修改')
    await author.getByText('修改意见（1）').click()
    await expect(author.getByText('请明确责任人和完成标准。')).toBeVisible()
    await author.getByRole('textbox', { name: '正文草稿' }).fill(revised)
    await author.getByRole('button', { name: '保存为新版本' }).click()
    await expect(author.getByText('编辑草稿 · 基于 v2')).toBeVisible()
    await author.getByRole('button', { name: '重新提交 v2' }).click()
    await expect(author.getByRole('region', { name: '文档评审状态' })).toContainText('绑定版本：v2')
    await author.screenshot({ path: testInfo.outputPath('document-desktop.png'), fullPage: true })
    await author.setViewportSize({ width: 390, height: 844 })
    expect(await author.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await author.screenshot({ path: testInfo.outputPath('document-mobile.png'), fullPage: true })

    await navigate(reviewer, '待我评审')
    await reviewer.getByRole('button', { name: new RegExp(title) }).click()
    await expect(reviewer.locator('.review-source')).toHaveText(revised)
    await expect(reviewer.locator('.review-panel')).toContainText('绑定版本：v2')
    await reviewer.getByRole('button', { name: '继续评审' }).click()
    await reviewer.getByRole('button', { name: '批准', exact: true }).click()
    await expect(reviewer.getByText('评审已通过。')).toBeVisible()
    await expect(reviewer.getByRole('tab', { name: '待我评审 0' })).toBeVisible()
    await author.getByRole('button', { name: '刷新状态' }).click()
    await expect(author.getByRole('region', { name: '文档评审状态' })).toContainText('已通过')
  } finally {
    await authorContext.close()
    await reviewerContext.close()
    await adminContext.close()
  }
})
