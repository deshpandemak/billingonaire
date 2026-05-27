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
    // HTML5 required validation prevents submission — URL stays on login
    await expect(page).toHaveURL(/.*login/);
  });

  test('should redirect to dashboard after successful login', async ({ page }) => {
    // Build a minimal Firebase-format JWT.
    // Firebase Web SDK does not verify JWT signatures client-side, so a
    // mock token with the required payload fields is sufficient.
    const now = Math.floor(Date.now() / 1000);
    const header = Buffer.from(JSON.stringify({ alg: 'RS256', kid: 'test' })).toString('base64url');
    const payload = Buffer.from(JSON.stringify({
      iss: 'https://securetoken.google.com/billingonaire',
      aud: 'billingonaire',
      sub: 'test_uid',
      user_id: 'test_uid',
      email: 'test@example.com',
      email_verified: true,
      auth_time: now,
      iat: now,
      exp: now + 3600,
      firebase: {
        identities: { email: ['test@example.com'] },
        sign_in_provider: 'password',
      },
    })).toString('base64url');
    const mockIdToken = `${header}.${payload}.mock_sig`;

    // Intercept the Firebase signInWithPassword REST call so tests do not
    // require a live Firebase project or emulator.
    await page.route('**/accounts:signInWithPassword**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          localId: 'test_uid',
          email: 'test@example.com',
          idToken: mockIdToken,
          refreshToken: 'mock-refresh-token',
          expiresIn: '3600',
          registered: true,
        }),
      })
    );

    await page.fill('input[type="email"]', 'test@example.com');
    await page.fill('input[type="password"]', 'testpassword123');
    await page.click('button[type="submit"]');

    await page.waitForURL(/.*dashboard/, { timeout: 8000 });
  });
});
