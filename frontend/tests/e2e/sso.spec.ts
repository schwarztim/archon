import { test, expect } from "@playwright/test";

test.describe("SSO Config Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/sso");
    await page.waitForLoadState("networkidle");

    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays H1 heading containing SSO", async ({ page }) => {
    await page.goto("/sso");
    await page.waitForLoadState("networkidle");

    await expect(page.locator("h1").first()).toContainText("SSO");
  });

  test("has Identity Providers tab", async ({ page }) => {
    await page.goto("/sso");
    await page.waitForLoadState("networkidle");

    const tab = page.locator('[role="tab"], button, [class*="tab"]', {
      hasText: /Identity Providers/i,
    }).first();
    await expect(tab).toBeVisible();
  });

  test("has RBAC Matrix tab", async ({ page }) => {
    await page.goto("/sso");
    await page.waitForLoadState("networkidle");

    const tab = page.locator('[role="tab"], button, [class*="tab"]', {
      hasText: /RBAC Matrix/i,
    }).first();
    await expect(tab).toBeVisible();
  });

  test("has Custom Roles tab", async ({ page }) => {
    await page.goto("/sso");
    await page.waitForLoadState("networkidle");

    const tab = page.locator('[role="tab"], button, [class*="tab"]', {
      hasText: /Custom Roles/i,
    }).first();
    await expect(tab).toBeVisible();
  });

  test("Identity Providers tab shows Add OIDC, Add SAML, Add LDAP buttons", async ({ page }) => {
    await page.goto("/sso");
    await page.waitForLoadState("networkidle");

    // Ensure the Identity Providers tab is active (click if needed)
    const idpTab = page.locator('[role="tab"], button, [class*="tab"]', {
      hasText: /Identity Providers/i,
    }).first();
    if (await idpTab.isVisible()) {
      await idpTab.click();
    }

    await expect(
      page.locator("button", { hasText: /Add OIDC/i }).first()
    ).toBeVisible();

    await expect(
      page.locator("button", { hasText: /Add SAML/i }).first()
    ).toBeVisible();

    await expect(
      page.locator("button", { hasText: /Add LDAP/i }).first()
    ).toBeVisible();
  });

  test("tabs are navigable", async ({ page }) => {
    await page.goto("/sso");
    await page.waitForLoadState("networkidle");

    const rbacTab = page.locator('[role="tab"], button, [class*="tab"]', {
      hasText: /RBAC Matrix/i,
    }).first();

    if (await rbacTab.isVisible()) {
      await rbacTab.click();
      const bodyText = await page.locator("body").innerText();
      expect(bodyText.trim().length).toBeGreaterThan(0);
    }

    const rolesTab = page.locator('[role="tab"], button, [class*="tab"]', {
      hasText: /Custom Roles/i,
    }).first();

    if (await rolesTab.isVisible()) {
      await rolesTab.click();
      const bodyText = await page.locator("body").innerText();
      expect(bodyText.trim().length).toBeGreaterThan(0);
    }
  });
});
