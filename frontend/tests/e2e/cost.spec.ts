import { test, expect } from "@playwright/test";

test.describe("Cost Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/cost");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays heading with Cost", async ({ page }) => {
    await page.goto("/cost");
    await page.waitForLoadState("networkidle");

    // H1 contains "Cost"
    const h1 = page.locator("h1").first();
    await expect(h1).toContainText("Cost");
  });

  test("renders page content without crash", async ({ page }) => {
    await page.goto("/cost");
    await page.waitForLoadState("networkidle");

    // Page should show either cost data sections or an error message
    const hasUsageText = await page.getByText(/usage/i).count();
    const hasErrorText = await page.getByText(/failed to load/i).count();
    const hasContent = hasUsageText > 0 || hasErrorText > 0;
    expect(hasContent).toBe(true);
  });
});
