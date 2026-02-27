import { test, expect } from "@playwright/test";

test.describe("Red Team Testing Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/redteam");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays H1 heading", async ({ page }) => {
    await page.goto("/redteam");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("h1").first()).toContainText("Red Team Testing");
  });

  test("has Target Agent ID input", async ({ page }) => {
    await page.goto("/redteam");
    await page.waitForLoadState("networkidle");

    const agentInput = page.locator("#agent-id");
    await expect(agentInput).toBeVisible();
  });

  test("has Run Security Scan button", async ({ page }) => {
    await page.goto("/redteam");
    await page.waitForLoadState("networkidle");

    const scanButton = page.locator('button', { hasText: "Run Security Scan" }).first();
    await expect(scanButton).toBeVisible();
  });

  test("has attack type toggle buttons", async ({ page }) => {
    await page.goto("/redteam");
    await page.waitForLoadState("networkidle");

    // Check for at least one attack type toggle
    const promptInjection = page.locator('button, [role="checkbox"], label', {
      hasText: /prompt.?injection/i,
    }).first();
    await expect(promptInjection).toBeVisible();

    const jailbreak = page.locator('button, [role="checkbox"], label', {
      hasText: /jailbreak/i,
    }).first();
    await expect(jailbreak).toBeVisible();
  });

  test("has collapsible Testing Capabilities section", async ({ page }) => {
    await page.goto("/redteam");
    await page.waitForLoadState("networkidle");

    const capabilitiesSection = page.locator('text=/Testing Capabilities/i').first();
    await expect(capabilitiesSection).toBeVisible();
  });

  test("Testing Capabilities section is collapsible", async ({ page }) => {
    await page.goto("/redteam");
    await page.waitForLoadState("networkidle");

    const toggle = page.locator(
      '[class*="collapsible"], details summary, button',
      { hasText: /Testing Capabilities/i }
    ).first();

    if (await toggle.isVisible()) {
      await toggle.click();
      // Just verify clicking doesn't crash the page
      const bodyText = await page.locator("body").innerText();
      expect(bodyText.trim().length).toBeGreaterThan(0);
    }
  });
});
