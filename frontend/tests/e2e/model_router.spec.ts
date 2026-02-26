import { test, expect } from '@playwright/test';

test.describe('Model Router Page', () => {
  test('loads model router page', async ({ page }) => {
    await page.goto('/router');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).not.toBeEmpty();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });

  test('displays provider list or model configuration UI', async ({ page }) => {
    await page.goto('/router');
    await page.waitForLoadState('networkidle');

    // Look for provider cards, model config forms, or routing rules
    const routerContent = page.locator(
      '[class*="provider"], [class*="model"], [class*="router"], [class*="route"], table, ul li, [role="listitem"], select, input'
    );
    const hasContent = await routerContent.count() > 0;

    if (!hasContent) {
      const bodyText = await page.locator('body').innerText();
      expect(bodyText.trim().length).toBeGreaterThan(10);
    } else {
      await expect(routerContent.first()).toBeVisible();
    }
  });

  test('no crash on router page', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.goto('/router');
    await page.waitForLoadState('networkidle');

    const criticalErrors = errors.filter(
      (e) =>
        !e.includes('Warning:') &&
        !e.includes('ResizeObserver') &&
        !e.includes('non-passive event listener')
    );
    expect(criticalErrors).toHaveLength(0);
  });
});
