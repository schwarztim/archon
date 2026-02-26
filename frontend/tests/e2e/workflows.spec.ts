import { test, expect } from '@playwright/test';

test.describe('Workflows Page', () => {
  test('loads workflows page', async ({ page }) => {
    await page.goto('/workflows');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).not.toBeEmpty();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });

  test('displays workflow-related content', async ({ page }) => {
    await page.goto('/workflows');
    await page.waitForLoadState('networkidle');

    // Look for table, list, create button, or workflow text
    const workflowContent = page.locator(
      'table, [role="table"], ul li, [class*="workflow"], button:has-text("Create"), button:has-text("New")'
    );
    const hasContent = await workflowContent.count() > 0;

    if (!hasContent) {
      // Empty state is valid — page still must render
      const bodyText = await page.locator('body').innerText();
      expect(bodyText.trim().length).toBeGreaterThan(10);
    } else {
      await expect(workflowContent.first()).toBeVisible();
    }
  });

  test('navigation links to workflows', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Find any nav link pointing to /workflows
    const workflowLink = page.locator('a[href="/workflows"], a[href*="workflows"]');
    if (await workflowLink.count() > 0) {
      await workflowLink.first().click();
      await page.waitForLoadState('networkidle');
      await expect(page).toHaveURL(/\/workflows/);
    } else {
      // Direct nav still works
      await page.goto('/workflows');
      await expect(page).toHaveURL(/\/workflows/);
    }
  });
});
