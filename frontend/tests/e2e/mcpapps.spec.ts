import { test, expect } from "@playwright/test";

test.describe("MCP Apps Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/mcp-apps");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays H1 heading", async ({ page }) => {
    await page.goto("/mcp-apps");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("h1").first()).toContainText("MCP Apps");
  });

  test("has search input", async ({ page }) => {
    await page.goto("/mcp-apps");
    await page.waitForLoadState("networkidle");

    const searchInput = page.locator("input[placeholder='Search apps\u2026']");
    await expect(searchInput).toBeVisible();
  });

  test("displays app cards in a grid", async ({ page }) => {
    await page.goto("/mcp-apps");
    await page.waitForLoadState("networkidle");

    // At least one app name should be visible
    await expect(page.getByText("Data Explorer").first()).toBeVisible();
  });

  test("search input is interactive", async ({ page }) => {
    await page.goto("/mcp-apps");
    await page.waitForLoadState("networkidle");

    const searchInput = page.locator("input[placeholder='Search apps\u2026']");
    await searchInput.fill("Data Explorer");
    await expect(searchInput).toHaveValue("Data Explorer");
  });
});
