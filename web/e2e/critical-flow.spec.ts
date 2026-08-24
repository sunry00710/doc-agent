import { expect, test } from '@playwright/test'

const username = process.env.DOC_AGENT_E2E_USERNAME
const password = process.env.DOC_AGENT_E2E_PASSWORD

test.describe('critical document workflow', () => {
  test.skip(!username || !password, 'Set DOC_AGENT_E2E_USERNAME and DOC_AGENT_E2E_PASSWORD for the authenticated flow')

  test('login, agent, citations, documents and knowledge surfaces', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('Username').fill(username!)
    await page.getByLabel('Password').fill(password!)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByText('Doc Agent').first()).toBeVisible()

    await page.getByRole('button', { name: 'Workspace' }).click()
    const composer = page.getByPlaceholder(/ask/i)
    if (await composer.count()) {
      await composer.fill('Summarize the current document context.')
      await page.getByRole('button', { name: /send/i }).click()
    }
    await page.screenshot({ path: 'test-results/critical-workspace.png', fullPage: true })

    await page.getByRole('button', { name: 'Documents' }).click()
    await expect(page.getByRole('heading', { name: 'Documents' })).toBeVisible()
    await page.getByRole('button', { name: 'Knowledge' }).click()
    await expect(page.getByRole('heading', { name: /knowledge/i })).toBeVisible()
  })
})
