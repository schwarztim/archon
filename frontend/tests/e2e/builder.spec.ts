import { test, expect } from "@playwright/test";

test.describe("Builder Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/builder");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays canvas or agent editor area", async ({ page }) => {
    await page.goto("/builder");
    await page.waitForLoadState("networkidle");

    // Look for canvas/node editor or default agent name
    const hasCanvas = await page.locator("canvas").count();
    const hasUntitled = await page
      .getByText(/untitled agent/i)
      .count();
    const hasNodeEditor = await page
      .locator("[class*='canvas'], [class*='editor'], [class*='flow'], [class*='board']")
      .count();

    expect(hasCanvas + hasUntitled + hasNodeEditor).toBeGreaterThan(0);
  });

  test("page body is not empty after navigation", async ({ page }) => {
    await page.goto("/builder");
    await page.waitForLoadState("networkidle");

    const body = page.locator("body");
    await expect(body).not.toBeEmpty();
  });
});
