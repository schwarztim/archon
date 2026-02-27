import { test, expect } from "@playwright/test";

test.describe("DocForge Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/docforge");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays H1 heading", async ({ page }) => {
    await page.goto("/docforge");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("h1").first()).toContainText("DocForge");
  });

  test("displays Documents and Collections tabs", async ({ page }) => {
    await page.goto("/docforge");
    await page.waitForLoadState("networkidle");

    await expect(page.getByText("Documents").first()).toBeVisible();
    await expect(page.getByText("Collections").first()).toBeVisible();
  });

  test("displays search input", async ({ page }) => {
    await page.goto("/docforge");
    await page.waitForLoadState("networkidle");

    await expect(
      page.locator('input[placeholder="Search documents..."]').first()
    ).toBeVisible();
  });

  test("displays Ingest Document button", async ({ page }) => {
    await page.goto("/docforge");
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByRole("button", { name: /ingest document/i }).first()
    ).toBeVisible();
  });
});
