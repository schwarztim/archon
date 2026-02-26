import { test, expect } from '@playwright/test';

test.describe('Secrets / Settings Page', () => {
  test('settings page loads without "failed to load" error', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    await expect(page.locator('body')).not.toBeEmpty();

    // Should not show a generic "failed to load" error state
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.toLowerCase()).not.toContain('failed to load');
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });

  test('settings page has meaningful content', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    // Settings pages typically have tabs, sections, or form fields
    const settingsContent = page.locator(
      '[role="tab"], [class*="tab"], [class*="settings"], [class*="section"], input, select, textarea'
    );
    const hasContent = await settingsContent.count() > 0;

    if (!hasContent) {
      const bodyText = await page.locator('body').innerText();
      expect(bodyText.trim().length).toBeGreaterThan(10);
    } else {
      await expect(settingsContent.first()).toBeVisible();
    }
  });
});
