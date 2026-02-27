import { test, expect } from "@playwright/test";

test.describe("Lifecycle Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/lifecycle");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays H1 heading containing Lifecycle", async ({ page }) => {
    await page.goto("/lifecycle");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("h1").first()).toContainText("Lifecycle");
  });

  test("displays tab navigation", async ({ page }) => {
    await page.goto("/lifecycle");
    await page.waitForLoadState("networkidle");

    // Tab buttons: Pipeline, Environments, History, Gates
    await expect(page.locator("button", { hasText: "Pipeline" }).first()).toBeVisible();
    await expect(page.locator("button", { hasText: "Environments" }).first()).toBeVisible();
    await expect(page.locator("button", { hasText: "History" }).first()).toBeVisible();
    await expect(page.locator("button", { hasText: "Gates" }).first()).toBeVisible();
  });

  test("displays Deploy button", async ({ page }) => {
    await page.goto("/lifecycle");
    await page.waitForLoadState("networkidle");

    await expect(
      page.locator("button", { hasText: /deploy/i }).first()
    ).toBeVisible();
  });
});
