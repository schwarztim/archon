import { test, expect } from '@playwright/test';

test.describe('System Health', () => {
  test('API health endpoint responds via frontend proxy', async ({ page }) => {
    const response = await page.request.get('/api/v1/health');
    expect(response.status()).toBe(200);
  });

  test('frontend app is functional', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // App should render — not show a blank page or crash screen
    await expect(page.locator('body')).not.toBeEmpty();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    // Should not show an unhandled error boundary
    const errorBoundary = page.locator(
      '[class*="error-boundary"], [data-testid="error"], h1:has-text("Something went wrong")'
    );
    expect(await errorBoundary.count()).toBe(0);
  });

  test('SPA routing does not 404', async ({ page }) => {
    const routes = ['/', '/audit', '/workflows', '/templates', '/settings'];
    for (const route of routes) {
      const response = await page.goto(route);
      // nginx should serve index.html for all SPA routes — no 404
      expect(response?.status()).not.toBe(404);
    }
  });
});
