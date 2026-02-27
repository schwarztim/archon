import { test, expect } from "@playwright/test";

// NOTE: sentinel.spec.ts already exists for general sentinel tests.
// This file tests the specific /sentinelscan route (SentinelScanPage).

test.describe("SentinelScan Page", () => {
  test("loads successfully without crash", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/sentinelscan");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);

    expect(errors).toHaveLength(0);
  });

  test("displays meaningful content", async ({ page }) => {
    await page.goto("/sentinelscan");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test("renders a visible heading or title", async ({ page }) => {
    await page.goto("/sentinelscan");
    await page.waitForLoadState("networkidle");

    // Should have at least one heading or meaningful title element
    const headings = page.locator("h1, h2, h3").first();
    await expect(headings).toBeVisible();
  });

  test("page has no critical JS errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/sentinelscan");
    await page.waitForLoadState("networkidle");

    // Interact briefly to trigger any lazy-loaded JS
    await page.mouse.move(400, 300);

    expect(errors).toHaveLength(0);
  });
});
