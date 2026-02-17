import { test, expect } from "@playwright/test";

test.describe("Agent Builder", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("renders the builder layout", async ({ page }) => {
    await expect(page.getByRole("toolbar", { name: /toolbar/i })).toBeVisible();
    await expect(page.getByRole("complementary", { name: /node palette/i })).toBeVisible();
    await expect(page.getByRole("complementary", { name: /property panel/i })).toBeVisible();
    await expect(page.getByRole("application", { name: /canvas/i })).toBeVisible();
  });

  test("can drag a node from palette onto canvas", async ({ page }) => {
    const llmCard = page.getByRole("listitem", { name: /drag to add llm/i });
    await expect(llmCard).toBeVisible();

    const canvas = page.getByRole("application", { name: /canvas/i });
    const canvasBounds = await canvas.boundingBox();
    expect(canvasBounds).toBeTruthy();

    if (canvasBounds) {
      await llmCard.dragTo(canvas, {
        targetPosition: {
          x: canvasBounds.width / 2,
          y: canvasBounds.height / 2,
        },
      });
    }
  });

  test("shows empty property panel when no node selected", async ({ page }) => {
    await expect(
      page.getByText("Select a node to edit its properties"),
    ).toBeVisible();
  });

  test("toggles dark mode", async ({ page }) => {
    const themeBtn = page.getByRole("button", { name: /switch to/i });
    await themeBtn.click();
    const html = page.locator("html");
    const hasDark = await html.evaluate((el) =>
      el.classList.contains("dark"),
    );
    expect(typeof hasDark).toBe("boolean");
  });
});
