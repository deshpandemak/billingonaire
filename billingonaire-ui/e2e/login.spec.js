import { test, expect } from '@playwright/test';

test.describe('Login Flow', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
  });

  test('should display login form', async ({ page }) => {
    await expect(page).toHaveTitle(/Billingonaire/);
    await expect(page.locator('input[type="email"]')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test('should show validation error for empty fields', async ({ page }) => {
    await page.click('button[type="submit"]');
    // Should stay on login page
    await expect(page).toHaveURL(/.*login/);
  });

  test('should redirect to dashboard after successful login', async ({ page }) => {
    // Mock Firebase Auth
    await page.addInitScript(() => {
      window.localStorage.setItem('authToken', 'test-token');
    });

    await page.fill('input[type="email"]', 'test@example.com');
    await page.fill('input[type="password"]', 'testpassword123');
    await page.click('button[type="submit"]');

    // Should redirect to dashboard
    await page.waitForURL(/.*dashboard/, { timeout: 5000 });
  });
});
