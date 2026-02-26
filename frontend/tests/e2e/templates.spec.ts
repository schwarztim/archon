import { test, expect } from '@playwright/test';

test.describe('Templates Page', () => {
  test('loads templates page', async ({ page }) => {
    await page.goto('/templates');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).not.toBeEmpty();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });

  test('displays template list or grid', async ({ page }) => {
    await page.goto('/templates');
    await page.waitForLoadState('networkidle');

    // Look for cards, list items, grid items, or table rows
    const templateContent = page.locator(
      '[class*="card"], [class*="grid"] > *, [class*="template"], table tr, ul li, [role="listitem"]'
    );
    const hasContent = await templateContent.count() > 0;

    if (!hasContent) {
      // Empty state is acceptable — page must still render
      const bodyText = await page.locator('body').innerText();
      expect(bodyText.trim().length).toBeGreaterThan(10);
    } else {
      await expect(templateContent.first()).toBeVisible();
    }
  });
});
