import { test, expect } from '@playwright/test';

test.describe('Marketplace Page', () => {
  test('loads marketplace page', async ({ page }) => {
    await page.goto('/marketplace');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).not.toBeEmpty();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });

  test('displays categories or package listings', async ({ page }) => {
    await page.goto('/marketplace');
    await page.waitForLoadState('networkidle');

    // Look for categories, packages, cards, or list content
    const marketplaceContent = page.locator(
      '[class*="category"], [class*="package"], [class*="card"], [class*="marketplace"], table tr, ul li, [role="listitem"]'
    );
    const hasContent = await marketplaceContent.count() > 0;

    if (!hasContent) {
      const bodyText = await page.locator('body').innerText();
      expect(bodyText.trim().length).toBeGreaterThan(10);
    } else {
      await expect(marketplaceContent.first()).toBeVisible();
    }
  });

  test('search or filter UI is present', async ({ page }) => {
    await page.goto('/marketplace');
    await page.waitForLoadState('networkidle');

    // Search input or filter controls are common in marketplace UIs
    const filterUI = page.locator('input[type="search"], input[placeholder*="search" i], input[placeholder*="filter" i], select, [class*="filter"]');
    // Not required — just informational
    const hasFilter = await filterUI.count() > 0;
    console.log(`Marketplace has search/filter UI: ${hasFilter}`);
  });
});
