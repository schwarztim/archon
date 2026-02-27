import { test, expect } from "@playwright/test";

test.describe("Agents Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/agents");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays key UI elements", async ({ page }) => {
    await page.goto("/agents");
    await page.waitForLoadState("networkidle");

    // H1 heading
    await expect(page.locator("h1").first()).toHaveText("Agents");

    // Search input
    await expect(
      page.getByPlaceholder("Search agents...")
    ).toBeVisible();

    // Create Agent button
    await expect(
      page.getByRole("button", { name: /create agent/i }).first()
    ).toBeVisible();

    // Grid / List view toggles
    await expect(
      page.getByRole("button", { name: "Grid view" })
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "List view" })
    ).toBeVisible();

    // Status filter dropdown
    await expect(
      page.locator("select, [role='combobox'], [role='listbox']").first()
    ).toBeVisible();
  });

  test("search input is interactive", async ({ page }) => {
    await page.goto("/agents");
    await page.waitForLoadState("networkidle");

    const search = page.getByPlaceholder("Search agents...");
    await search.fill("test");
    await expect(search).toHaveValue("test");
  });

  test("can toggle between grid and list view", async ({ page }) => {
    await page.goto("/agents");
    await page.waitForLoadState("networkidle");

    await page.getByRole("button", { name: "List view" }).click();
    await page.getByRole("button", { name: "Grid view" }).click();
  });
});
