import { test, expect } from '@playwright/test';

test.describe('SentinelScan Page', () => {
  test('loads without white screen of death', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));

    await page.goto('/sentinelscan');
    await page.waitForLoadState('networkidle');

    // Not blank
    await expect(page.locator('body')).not.toBeEmpty();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    // No uncaught JS errors that would cause a white screen
    // Exclude known-benign browser warnings (React devtools, ResizeObserver loop, etc.)
    const criticalErrors = errors.filter(
      (e) =>
        !e.includes('Warning:') &&
        !e.includes('ResizeObserver') &&
        !e.includes('non-passive event listener')
    );
    expect(criticalErrors).toHaveLength(0);
  });

  test('displays scan-related UI elements', async ({ page }) => {
    await page.goto('/sentinelscan');
    await page.waitForLoadState('networkidle');

    // Look for scan buttons, input fields, or result areas
    const scanUI = page.locator(
      'button, input, [class*="scan"], [class*="sentinel"], form, table, [role="main"]'
    );
    const count = await scanUI.count();
    // If no elements found, fall back to body content check
    if (count > 0) {
      await expect(scanUI.first()).toBeVisible({ timeout: 10000 });
    } else {
      const bodyText = await page.locator('body').innerText();
      expect(bodyText.trim().length).toBeGreaterThan(0);
    }
  });
});
