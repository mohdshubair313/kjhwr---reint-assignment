import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { readFile } from 'node:fs/promises'

test('day replay reconciles with the API and renders charts, table and provenance', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  const api = await (await request.get('http://127.0.0.1:18261/api/evaluation?decision_start=2026-01-15&decision_end=2026-01-15')).json()
  await page.goto('/')
  await expect(page.getByTestId('dashboard')).toBeVisible()
  await expect(page.locator('.stat-value').first()).toContainText(new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 }).format(api.summary.mae_mw))
  await expect(page.getByText('24 of 24 delivery hours')).toBeVisible()
  await expect(page.locator('.chart-space .recharts-surface')).toBeVisible()
  await page.getByText('Inspect the hourly data', { exact: true }).click()
  await expect(page.locator('tbody tr')).toHaveCount(24)
  await expect(page.locator('tbody tr').first()).toContainText('00:00–01:00')
  await expect(page.locator('tbody tr').first()).toContainText('15 Jan · 07:30 GMT')
  await page.getByRole('checkbox', { name: 'Show actuals' }).uncheck()
  await expect(page.getByRole('checkbox', { name: 'Show actuals' })).not.toBeChecked()
  await page.getByRole('checkbox', { name: 'Show actuals' }).check()
  await page.getByText('Inspect the hourly data', { exact: true }).click()
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }))
  await page.screenshot({ path: '../artifacts/dashboard-desktop.png', fullPage: true })
  await page.getByRole('button', { name: 'Methodology', exact: true }).click()
  await expect(page.getByText('From source to screen')).toBeVisible()
  expect(errors).toEqual([])
})

test('date and cutoff apply together, including February delivery boundary', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('dashboard')).toBeVisible()
  await page.getByLabel('Decision date', { exact: true }).fill('2026-01-31')
  await page.getByLabel('Decision cutoff').fill('10:00')
  await expect(page.getByText('Changes not yet applied')).toBeVisible()
  await page.getByRole('button', { name: 'Apply changes' }).click()
  await expect(page.getByText('1 Feb 2026 · Hourly generation · MW')).toBeVisible()
  await expect(page.getByText('31 Jan · 10:00 GMT')).toBeVisible()
  await expect(page).toHaveURL(/date=2026-01-31&cutoff=10%3A00/)
  await page.reload()
  await expect(page.getByText('1 Feb 2026 · Hourly generation · MW')).toBeVisible()
})

test('monthly review exports all hours and can replay a selected day', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('dashboard')).toBeVisible()
  await page.getByRole('group', { name: 'Analysis view' }).getByRole('button', { name: 'January review' }).click()
  await expect(page.getByText('744 of 744 delivery hours')).toBeVisible()
  await expect(page.locator('.stat-value').first()).toContainText('2,038.9')
  await page.screenshot({ path: '../artifacts/dashboard-month.png', fullPage: true })
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('reint-january-2026-0900.csv')
  const path = await download.path()
  const csv = await readFile(path!, 'utf8')
  expect(csv.split('\r\n')).toHaveLength(745)
  expect(csv).toContain('"2026-02-01T23:00:00Z"')
  await page.getByText('Daily performance ledger', { exact: true }).click()
  await page.getByRole('button', { name: 'Replay 1 Jan', exact: true }).click()
  await expect(page.getByText('2 Jan 2026 · Hourly generation · MW')).toBeVisible()
})

test('upstream unavailable state can recover without showing stale results', async ({ page }) => {
  let fail = true
  await page.route('**/api/evaluation?*', route => fail ? route.fulfill({ status: 503, json: { detail: 'Unavailable' } }) : route.continue())
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('temporarily unavailable')
  await expect(page.getByRole('button', { name: 'Export CSV' })).toBeDisabled()
  await expect(page.getByTestId('dashboard')).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByTestId('dashboard')).toBeVisible()
})

test('no complete pairs show null metrics and explicit chart gaps', async ({ page }) => {
  await page.route('**/api/evaluation?*', async route => {
    const response = await route.fetch()
    const data = await response.json()
    const day = data.days.find((d: { decision_date: string }) => d.decision_date === '2026-01-15')
    Object.assign(day.metrics, { paired_hours: 0, actual_hours: 0, coverage: 0, mae_mw: null, bias_mw: null, rmse_mw: null, p90_absolute_error_mw: null, signed_energy_error_mwh: null })
    for (const row of data.rows.filter((r: { decision_date: string }) => r.decision_date === '2026-01-15')) Object.assign(row, { actual_mw: null, error_mw: null, absolute_error_mw: null, energy_error_mwh: null, paired: false, quality_flags: ['missing_actual_half_hour'] })
    await route.fulfill({ response, json: data })
  })
  await page.goto('/')
  await expect(page.getByText('No complete forecast–actual pairs')).toBeVisible()
  await expect(page.locator('.stat-value').first()).toHaveText('—MW')
  await expect(page.getByText('No paired observations to calculate errors.')).toBeVisible()
  await expect(page.getByText('0 of 24 delivery hours')).toBeVisible()
})

test('mismatched snapshot responses are not combined', async ({ page }) => {
  await page.route('**/api/metadata', async route => {
    const response = await route.fetch()
    await route.fulfill({ response, json: { ...await response.json(), snapshot_id: 'different-version' } })
  })
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('dataset changed')
  await expect(page.getByTestId('dashboard')).toHaveCount(0)
})

test('mobile layout fits the viewport and supports both views', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByTestId('dashboard')).toBeVisible()
  await expect(page.locator('.chart-space .recharts-surface')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: '../artifacts/dashboard-mobile.png', fullPage: true })
  await page.getByRole('group', { name: 'Analysis view' }).getByRole('button', { name: 'January review' }).click()
  await expect(page.getByText('744 of 744 delivery hours')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('dashboard meets automated accessibility checks', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('dashboard')).toBeVisible()
  await expect(page.locator('.chart-space .recharts-surface')).toBeVisible()
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  expect(results.violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })) }))).toEqual([])
})
