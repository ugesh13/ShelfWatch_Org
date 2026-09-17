import { expect, test, type Page } from '@playwright/test';

async function ready(page: Page) {
  await expect(page.getByRole('button', { name: 'Run Simulation', exact: true })).toBeEnabled({ timeout: 60_000 });
}

async function fixture(page: Page, fixtureId: string) {
  await page.locator('header select').nth(1).selectOption(fixtureId);
  await ready(page);
}

test.beforeEach(async ({ page }) => {
  // The local dashboard must remain usable when the optional online basemap fails.
  await page.route('https://*.tile.openstreetmap.org/**', (route) => route.abort());
  await page.goto('/');
  await ready(page);
});

test('switching medicine preserves the selected fixture and scenario', async ({ page }) => {
  await fixture(page, 'healthy_supply');
  const newScenarios: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/api/scenarios')) {
      newScenarios.push(request.postData() || '');
    }
  });
  const completed = page.waitForResponse((response) =>
    response.url().endsWith('/run') && response.request().postDataJSON()?.sku_id === 'PCM500_TAB');
  await page.locator('header select').nth(0).selectOption('PCM500_TAB');
  await completed;
  await ready(page);
  await expect(page.locator('header select').nth(0)).toHaveValue('PCM500_TAB');
  await expect(page.locator('header select').nth(1)).toHaveValue('healthy_supply');
  expect(newScenarios).toEqual([]);
});

test('editing another SKU keeps existing demand assumptions', async ({ page }) => {
  await fixture(page, 'mixed_pressure');
  await page.locator('header select').nth(0).selectOption('PCM500_TAB');
  await ready(page);
  const patchRequest = page.waitForRequest((request) => request.method() === 'PATCH');
  await page.getByRole('button', { name: 'Apply What-If & Re-simulate' }).click();
  const patch = (await patchRequest).postDataJSON();
  expect(patch.demand_overrides).toContainEqual(expect.objectContaining({
    facility_id: 'F-01', sku_id: 'AMX500_CAP', multiplier: 2,
  }));
  expect(patch.demand_overrides.some((item: { sku_id: string }) => item.sku_id === 'PCM500_TAB')).toBe(false);
  await ready(page);
});

test('approval records a proposal and survives recalculation', async ({ page }, testInfo) => {
  await page.getByRole('button', { name: 'Approve Plan', exact: true }).click();
  await expect(page.getByText('AUDIT STATUS: APPROVED', { exact: true })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath('dashboard-desktop.png'), fullPage: true });
  await expect(page.getByText(/orders dispatched/i)).toHaveCount(0);
  await page.getByRole('button', { name: 'Run Simulation', exact: true }).click();
  await ready(page);
  await expect(page.getByText('AUDIT STATUS: APPROVED', { exact: true })).toBeVisible();
});

test('a superseded response cannot overwrite the active medicine', async ({ page }) => {
  await fixture(page, 'healthy_supply');
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let intercepted: () => void = () => {};
  const started = new Promise<void>((resolve) => { intercepted = resolve; });
  await page.route('**/api/scenarios/*/run', async (route) => {
    if (route.request().postDataJSON().sku_id !== 'PCM500_TAB') return route.continue();
    const response = await route.fetch();
    intercepted();
    await gate;
    await route.fulfill({ response }).catch(() => {});
  });
  await page.locator('header select').nth(0).selectOption('PCM500_TAB');
  await started;
  await page.locator('header select').nth(0).selectOption('ORS1L_SACHET');
  await ready(page);
  release();
  await expect(page.getByTestId('plan-comparison')).toHaveAttribute('data-sku-id', 'ORS1L_SACHET');
  await expect(page.locator('header select').nth(0)).toHaveValue('ORS1L_SACHET');
});

test('unknown evidence stays unknown in the drawer and Escape closes it', async ({ page }) => {
  await fixture(page, 'incomplete_records');
  await page.getByLabel('Inspect facility').selectOption('F-01');
  const drawer = page.getByRole('dialog');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText('Unknown', { exact: true }).first()).toBeVisible();
  await expect(drawer.getByText('0%', { exact: true })).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(drawer).not.toBeVisible();
});

test('a maximum depot delay remains runnable', async ({ page }) => {
  await page.getByLabel('North Depot Extra Delay').fill('14');
  await page.getByRole('button', { name: 'Apply What-If & Re-simulate' }).click();
  await ready(page);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByTestId('plan-comparison')).toBeVisible();
});

test('mobile controls and facility inspection remain reachable', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('dashboard-mobile.png'), fullPage: true });
  await page.getByLabel('Inspect facility').selectOption('F-A');
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog').getByText('High risk', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('facility-mobile.png') });
  await page.getByRole('button', { name: 'Close facility details' }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
});

test('a failed forecast stays unavailable and recovers on rerun', async ({ page }) => {
  await page.route('**/api/scenarios/*/run', (route) => route.fulfill({
    status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Test forecast failure' }),
  }));
  await page.getByRole('button', { name: 'Run Simulation', exact: true }).click();
  await ready(page);
  await expect(page.getByRole('alert')).toContainText('Unavailable: inventory forecast');
  await expect(page.getByText('Forecast unavailable', { exact: true })).toBeVisible();
  await expect(page.getByTestId('plan-comparison')).toBeVisible();
  await page.unroute('**/api/scenarios/*/run');
  await page.getByRole('button', { name: 'Run Simulation', exact: true }).click();
  await ready(page);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByText('Forecast unavailable', { exact: true })).toHaveCount(0);
});

test('failed facility detail can retry and restores keyboard focus', async ({ page }) => {
  const detailRoute = '**/api/scenarios/*/facilities/F-A?*';
  await page.route(detailRoute, (route) => route.fulfill({
    status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Test detail failure' }),
  }));
  const selector = page.getByLabel('Inspect facility');
  await selector.focus();
  await selector.selectOption('F-A');
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByRole('alert')).toContainText('Facility details unavailable');
  await page.unroute(detailRoute);
  await drawer.getByRole('button', { name: 'Retry facility details' }).click();
  await expect(drawer.getByText('High risk', { exact: true })).toBeVisible();
  await drawer.getByRole('button', { name: 'Close facility details' }).focus();
  await page.keyboard.press('Shift+Tab');
  expect(await page.evaluate(() => Boolean(document.activeElement?.closest('dialog')))).toBe(true);
  await page.keyboard.press('Escape');
  await expect(drawer).not.toBeVisible();
  await expect(selector).toBeFocused();
});

test('closing a route removes its transfer and leaves the new revision unapproved', async ({ page }) => {
  await page.getByRole('button', { name: 'Approve Plan', exact: true }).click();
  await expect(page.getByText('AUDIT STATUS: APPROVED', { exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: 'Close transfer route B_TO_A' }).check();
  await page.getByRole('button', { name: 'Apply What-If & Re-simulate' }).click();
  await ready(page);
  const plan = page.getByTestId('plan-comparison');
  await expect(plan.getByText('Recipient: F-A', { exact: true })).toHaveCount(0);
  await expect(plan.getByText('Recipient: F-C', { exact: true })).toBeVisible();
  await expect(page.getByText('AUDIT STATUS: APPROVED', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Approve Plan', exact: true })).toBeEnabled();
});
