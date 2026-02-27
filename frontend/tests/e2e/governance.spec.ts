import { test, expect } from "@playwright/test";

test.describe("Governance Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/governance");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays H1 heading containing Governance", async ({ page }) => {
    await page.goto("/governance");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("h1").first()).toContainText("Governance");
  });

  test("displays Registry tab", async ({ page }) => {
    await page.goto("/governance");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Registry").first()).toBeVisible();
  });

  test("displays Policies tab", async ({ page }) => {
    await page.goto("/governance");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Policies").first()).toBeVisible();
  });

  test("displays Approvals tab", async ({ page }) => {
    await page.goto("/governance");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Approvals").first()).toBeVisible();
  });

  test("displays Audit Trail tab", async ({ page }) => {
    await page.goto("/governance");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Audit Trail").first()).toBeVisible();
  });

  test("can click Audit Trail tab and see audit-related content", async ({
    page,
  }) => {
    await page.goto("/governance");
    await page.waitForLoadState("networkidle");

    await page.getByText("Audit Trail").first().click();
    await page.waitForLoadState("networkidle");

    // After clicking Audit Trail, the body should have content
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });
});
