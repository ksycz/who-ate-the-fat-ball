import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, firstVisitId, isPhone, reseed, test } from "./helpers";

// Playing a visit marks it watched, so start from the seeded day, whatever ran before, and leave it that way.
test.beforeEach(async ({ request }) => {
  await reseed(request);
});

test.afterAll(async ({ request }) => {
  await reseed(request);
});

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

test("Stats", async ({ page }) => {
  await page.goto("/stats");
  await expect(page.getByRole("heading", { name: "Stats", level: 1 })).toBeVisible();
  await noViolations(page);
});

test("By species", async ({ page }) => {
  await page.goto("/birds/species");
  await expect(page.getByRole("link", { name: /Great tit/ })).toBeVisible();
  await noViolations(page);
});

test("a species' visits", async ({ page }) => {
  await page.goto("/birds/species/Parus%20major");
  await expect(page.getByRole("heading", { name: "Great tit", level: 1 })).toBeVisible();
  await noViolations(page);
});

test("Other with Empty clips chosen", async ({ page }) => {
  await page.goto("/other");
  await page.getByRole("group", { name: "Show" }).getByRole("button", { name: "Empty clips" }).click();
  await expect(page.getByRole("link", { name: /Empty clip/ })).toBeVisible();
  await noViolations(page);
});

test("Other with Only dogs chosen", async ({ page }) => {
  await page.goto("/other");
  await page.getByRole("group", { name: "Show" }).getByRole("button", { name: "Only dogs" }).click();
  await expect(page.getByRole("link", { name: /Dog/ })).toBeVisible();
  await noViolations(page);
});

test("Birds with the select bar open", async ({ page }) => {
  await page.goto("/birds");
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("checkbox", { name: /^Select / }).first().check();
  await expect(page.getByRole("region", { name: "Selected visits" })).toBeVisible();
  await noViolations(page);
});

test("the card menu open", async ({ page }) => {
  test.skip(isPhone(page), "the ⋯ menu is for big screens");
  await page.goto("/birds");
  await page.getByRole("button", { name: /^More actions for / }).first().click();
  await expect(page.getByRole("menu", { name: "Move to" })).toBeVisible();
  await noViolations(page);
});

test("the .zip dialog", async ({ page }) => {
  await page.goto("/birds");
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("checkbox", { name: /^Select / }).first().check();
  await page.getByRole("button", { name: "Download .zip" }).click();
  await expect(page.getByRole("dialog").getByText(/^Download 1 visit \(/)).toBeVisible();
  await noViolations(page);
});

test("the delete dialog", async ({ page }) => {
  await page.goto("/other");
  await page.getByRole("group", { name: "Show" }).getByRole("button", { name: "Empty clips" }).click();
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("button", { name: "Select all" }).click();
  await page.getByRole("region", { name: "Selected visits" }).getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("dialog").getByText(/^Delete 1 empty clip/)).toBeVisible();
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
