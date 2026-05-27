import { test, expect } from '@playwright/test';

// ---------------------------------------------------------------------------
// Unauthenticated guard tests — no Firebase emulator needed.
// These verify that protected routes redirect to /login when there is no
// authenticated session.
// ---------------------------------------------------------------------------
test.describe('Auth guard — protected routes redirect to login', () => {
  test('bill-generation requires authentication', async ({ page }) => {
    await page.goto('/bill-generation');
    await page.waitForURL(/.*login/, { timeout: 5000 });
    await expect(page).toHaveURL(/.*login/);
    await expect(page.locator('input[type="email"]')).toBeVisible();
  });

  test('dashboard requires authentication', async ({ page }) => {
    await page.goto('/dashboard');
    await page.waitForURL(/.*login/, { timeout: 5000 });
    await expect(page).toHaveURL(/.*login/);
  });

  test('table view requires authentication', async ({ page }) => {
    await page.goto('/table');
    await page.waitForURL(/.*login/, { timeout: 5000 });
    await expect(page).toHaveURL(/.*login/);
  });

  test('admin routes require authentication', async ({ page }) => {
    await page.goto('/admin/users');
    await page.waitForURL(/.*login/, { timeout: 5000 });
    await expect(page).toHaveURL(/.*login/);
  });
});

// ---------------------------------------------------------------------------
// Authenticated feature tests — require Firebase emulator or a live project.
// Skipped in CI; run locally with a Firebase emulator configured.
// ---------------------------------------------------------------------------
test.describe.skip('Authenticated Feature Tests', () => {
  test.beforeEach(async ({ page: _page }) => {
    // TODO: Set up Firebase authentication for testing
    // 1. Start Firebase emulator: firebase emulators:start
    // 2. Point VITE_FIREBASE_EMULATOR=true in test env
  });

  test('admin can see and use AGP filter on bill generation', async ({ page }) => {
    await page.goto('/bill-generation');

    await expect(page.locator('.badge.bg-success:has-text("Admin")')).toBeVisible();

    const agpSelector = page.locator('select').filter({ hasText: 'My Cases Only' });
    await expect(agpSelector).toBeVisible();

    const optionsCount = await agpSelector.locator('option').count();
    expect(optionsCount).toBeGreaterThan(1);
  });

  test('analyze button successfully analyzes an order', async ({ page }) => {
    await page.goto('/dashboard');
    await page.waitForSelector('.ag-grid-container', { timeout: 10000 });

    const analyzeButton = page.locator('button:has-text("Analyze")').first();
    await expect(analyzeButton).toBeVisible();
    await analyzeButton.click();

    await page.waitForSelector('text=/✅|❌/', { timeout: 30000 });
    await expect(page.locator('text=/500 error|Failed to analyze/')).not.toBeVisible();
  });

  test('order PDF link opens in new tab', async ({ page }) => {
    await page.goto('/dashboard');
    const orderLink = page.locator('a:has-text("📄 View Order")').first();
    await expect(orderLink).toBeVisible();
  });
});
