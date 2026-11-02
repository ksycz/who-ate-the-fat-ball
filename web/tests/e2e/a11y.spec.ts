import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, firstVisitId, test } from "./helpers";

async function noViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
}

test("Today", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Checking who it is…")).toBeVisible();
  await noViolations(page);
});

test("Visit", async ({ page, request }) => {
  await page.goto(`/visit/${await firstVisitId(request)}`);
  await expect(page.getByRole("button", { name: "Not right? Change" })).toBeVisible();
  await noViolations(page);
});

test("the open picker", async ({ page, request }) => {
  await page.goto(`/visit/${await firstVisitId(request)}`);
  await page.getByRole("button", { name: "Not right? Change" }).click();
  await expect(page.getByText("Birds seen at your feeder")).toBeVisible();
  await expect(page.getByRole("button", { name: /^Great tit/ })).toBeVisible();
  await noViolations(page);
});

test("Birds", async ({ page }) => {
  await page.goto("/birds");
  await expect(page.getByRole("heading", { name: "Yesterday", level: 2 })).toBeVisible();
  await noViolations(page);
});

test("Other", async ({ page }) => {
  await page.goto("/other");
  await expect(page.getByRole("link", { name: /Dog/ })).toBeVisible();
  await noViolations(page);
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } }); // More is a phone-only page

  test("More", async ({ page }) => {
    await page.goto("/more");
    await expect(page.getByRole("link", { name: /App status/ })).toContainText("Camera seen");
    await noViolations(page);
  });
});

test("App status", async ({ page }) => {
  await page.goto("/status");
  await expect(page.getByText("Last seen: 09:58")).toBeVisible();
  await noViolations(page);
});

test("Unlock", async ({ page }) => {
  await page.goto("/unlock");
  await expect(page.getByLabel("Edit PIN")).toBeVisible();
  await noViolations(page);
});
