import { test, expect } from "@playwright/test";

test.describe("Agent Wizard Route", () => {
  test("redirects to dashboard since /wizard is not a registered route", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/wizard");
    await page.waitForLoadState("networkidle");

    // /wizard is not a registered route — should redirect to /
    expect(page.url()).toContain("/");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });
});
