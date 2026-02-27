import { test, expect } from "@playwright/test";

test.describe("DLP Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/dlp");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays heading and tab buttons", async ({ page }) => {
    await page.goto("/dlp");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("h1").first()).toHaveText("Data Loss Prevention");

    // All four tab labels should be visible in the tab bar
    await expect(page.getByText("Dashboard").first()).toBeVisible();
    await expect(page.getByText("Test Scanner").first()).toBeVisible();
    await expect(page.getByText("Detections").first()).toBeVisible();
  });

  test("Policies tab shows create button or policies table", async ({ page }) => {
    await page.goto("/dlp");
    await page.waitForLoadState("networkidle");

    // Click the Policies tab button specifically
    const policiesTab = page.locator("button", { hasText: "Policies" }).first();
    await policiesTab.click();
    await page.waitForLoadState("networkidle");

    const hasCreateBtn = await page.getByRole("button", { name: /create policy/i }).count();
    const hasTable = await page.locator("table").count();

    expect(hasCreateBtn + hasTable).toBeGreaterThan(0);
  });
});
