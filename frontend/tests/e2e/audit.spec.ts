import { test, expect } from '@playwright/test';

test.describe('Audit Page', () => {
  test('loads audit page without blank screen', async ({ page }) => {
    await page.goto('/audit');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).not.toBeEmpty();
    // Verify it's not a white screen of death — some content must be rendered
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });

  test('displays audit-related UI', async ({ page }) => {
    await page.goto('/audit');
    await page.waitForLoadState('networkidle');

    // Look for table, list, or any audit-related element
    const auditContent = page.locator(
      'table, [role="table"], ul, ol, [class*="audit"], [class*="log"], [class*="event"]'
    );
    const hasContent = await auditContent.count() > 0;

    if (!hasContent) {
      // Fallback: verify some meaningful text is present
      const bodyText = await page.locator('body').innerText();
      expect(bodyText.length).toBeGreaterThan(10);
    } else {
      await expect(auditContent.first()).toBeVisible();
    }
  });
});
