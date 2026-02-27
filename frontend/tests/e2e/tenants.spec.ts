import { test, expect } from "@playwright/test";

test.describe("Tenants Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/tenants");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays H1 heading", async ({ page }) => {
    await page.goto("/tenants");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("h1").first()).toContainText("Tenants");
  });

  test("has Create Tenant button", async ({ page }) => {
    await page.goto("/tenants");
    await page.waitForLoadState("networkidle");

    const createButton = page.locator("button", { hasText: /Create Tenant/i }).first();
    await expect(createButton).toBeVisible();
  });

  test("displays tenant table or empty state", async ({ page }) => {
    await page.goto("/tenants");
    await page.waitForLoadState("networkidle");

    // Either a table with rows or an empty state message should be present
    const tableOrEmptyState = page.locator(
      'table, [class*="table"], [class*="empty"], [class*="no-data"], tbody tr, [role="row"]'
    ).first();

    const bodyText = await page.locator("body").innerText();

    // Page should have meaningful content (table or empty state message)
    const hasTable = await tableOrEmptyState.isVisible().catch(() => false);
    const hasEmptyText = bodyText.match(/no tenants|empty|no results|get started/i);

    expect(hasTable || hasEmptyText).toBeTruthy();
  });

  test("Create Tenant button is clickable", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/tenants");
    await page.waitForLoadState("networkidle");

    const createButton = page.locator("button", { hasText: /Create Tenant/i }).first();
    await createButton.click();

    // After clicking, page should still be functional (no crash)
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });
});
