import { test, expect } from "@playwright/test";

test.describe("Login Page", () => {
  test("loads successfully", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    // In AUTH_DEV_MODE the page may redirect — just check body has content
    const bodyText = await page.locator("body").innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);

    expect(errors).toHaveLength(0);
  });

  test("displays sign-in heading or redirects gracefully", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    const currentUrl = page.url();
    if (currentUrl.includes("/login")) {
      // Login page still shown — check for heading
      const heading = page
        .getByRole("heading", { name: /sign in/i })
        .or(page.locator("h1").first());
      await expect(heading.first()).toBeVisible();
    } else {
      // Redirected due to AUTH_DEV_MODE — verify body has content
      const bodyText = await page.locator("body").innerText();
      expect(bodyText.trim().length).toBeGreaterThan(0);
    }
  });

  test("displays email input when on login page", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    if (!page.url().includes("/login")) {
      test.skip();
      return;
    }

    await expect(page.locator("#login-email")).toBeVisible();
    const emailInput = page.locator("#login-email");
    await expect(emailInput).toHaveAttribute("placeholder", "you@company.com");
  });

  test("displays password input when on login page", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    if (!page.url().includes("/login")) {
      test.skip();
      return;
    }

    await expect(page.locator("#login-password")).toBeVisible();
    const passwordInput = page.locator("#login-password");
    await expect(passwordInput).toHaveAttribute("type", "password");
  });

  test("displays Sign in submit button when on login page", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    if (!page.url().includes("/login")) {
      test.skip();
      return;
    }

    await expect(
      page.getByRole("button", { name: /^sign in$/i }).first()
    ).toBeVisible();
  });

  test("displays Sign in with SSO button when on login page", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    if (!page.url().includes("/login")) {
      test.skip();
      return;
    }

    await expect(
      page.getByRole("button", { name: /sign in with sso/i }).first()
    ).toBeVisible();
  });

  test("displays Remember me checkbox when on login page", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    if (!page.url().includes("/login")) {
      test.skip();
      return;
    }

    await expect(
      page.getByRole("checkbox", { name: /remember me/i }).first()
    ).toBeVisible();
  });
});
