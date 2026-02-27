import { test, expect } from "@playwright/test";

test.describe("Connectors Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/connectors");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays key UI elements", async ({ page }) => {
    await page.goto("/connectors");
    await page.waitForLoadState("networkidle");

    // H1 heading
    await expect(page.locator("h1").first()).toHaveText("Connectors");

    // Connector catalog — should show at least one well-known connector name
    const postgresText = page.getByText("PostgreSQL").first();
    await expect(postgresText).toBeVisible();
  });

  test("connector catalog shows multiple types", async ({ page }) => {
    await page.goto("/connectors");
    await page.waitForLoadState("networkidle");

    // Verify several connector types are visible
    await expect(page.getByText("PostgreSQL").first()).toBeVisible();
    await expect(page.getByText("MongoDB").first()).toBeVisible();

    // The catalog has a search input
    await expect(page.getByPlaceholder("Search connectors…")).toBeVisible();
  });
});
