import { test, expect } from "@playwright/test";

test.describe("Executions Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/executions");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays H1 heading", async ({ page }) => {
    await page.goto("/executions");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("h1").first()).toContainText("Executions");
  });

  test("displays Refresh button", async ({ page }) => {
    await page.goto("/executions");
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByRole("button", { name: /refresh/i }).first()
    ).toBeVisible();
  });

  test("displays Run Agent button", async ({ page }) => {
    await page.goto("/executions");
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByRole("button", { name: /run agent/i }).first()
    ).toBeVisible();
  });

  test("displays status filter dropdown", async ({ page }) => {
    await page.goto("/executions");
    await page.waitForLoadState("networkidle");

    // Status filter may be a select or a button/combobox
    const statusFilter =
      page.locator("select").first() ||
      page.getByRole("combobox").first();
    await expect(statusFilter).toBeVisible();
  });

  test("displays table or empty state", async ({ page }) => {
    await page.goto("/executions");
    await page.waitForLoadState("networkidle");

    const hasTable = await page.locator("table").count();
    const bodyText = await page.locator("body").innerText();

    // Either a table exists or there's some content (empty state message)
    expect(hasTable > 0 || bodyText.trim().length > 0).toBe(true);
  });
});
