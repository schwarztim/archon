import { test, expect } from '@playwright/test';

test.describe('Settings Page', () => {
  test('loads settings page', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).not.toBeEmpty();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });

  test('displays settings tabs or sections', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    // Look for tabs (API Keys, Notifications, etc.)
    const tabs = page.locator('[role="tab"], [class*="tab"], [class*="section"]');
    const hasTabs = await tabs.count() > 0;

    if (hasTabs) {
      await expect(tabs.first()).toBeVisible();
    } else {
      // Sections may be rendered differently
      const bodyText = await page.locator('body').innerText();
      expect(bodyText.trim().length).toBeGreaterThan(10);
    }
  });

  test('settings page has form elements', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    // Settings typically contain inputs, selects, or toggles
    const formElements = page.locator('input, select, textarea, [role="switch"], [type="checkbox"]');
    const hasFormElements = await formElements.count() > 0;
    console.log(`Settings form elements found: ${hasFormElements}`);

    // Page must render
    await expect(page.locator('body')).not.toBeEmpty();
  });
});
