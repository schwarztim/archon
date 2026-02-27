import { test, expect } from "@playwright/test";

test.describe("Guardrails Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/guardrails");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays H1 heading", async ({ page }) => {
    await page.goto("/guardrails");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("h1").first()).toContainText("Guardrails");
  });

  test("displays content textarea", async ({ page }) => {
    await page.goto("/guardrails");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("#guardrail-content")).toBeVisible();
  });

  test("displays direction select", async ({ page }) => {
    await page.goto("/guardrails");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("#guardrail-direction")).toBeVisible();
  });

  test("displays Check Guardrails button", async ({ page }) => {
    await page.goto("/guardrails");
    await page.waitForLoadState("networkidle");

    await expect(
      page.getByRole("button", { name: /check guardrails/i }).first()
    ).toBeVisible();
  });

  test("displays Go to DLP Policies link or button", async ({ page }) => {
    await page.goto("/guardrails");
    await page.waitForLoadState("networkidle");

    // Could be a link or a button
    const dlpLink = page
      .getByRole("link", { name: /dlp policies/i })
      .or(page.getByRole("button", { name: /dlp policies/i }))
      .first();
    await expect(dlpLink).toBeVisible();
  });
});
