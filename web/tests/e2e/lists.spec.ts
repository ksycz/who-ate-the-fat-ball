import { expect, reseed, test } from "./helpers";

// These specs change data: start each one from the seeded day, and leave it that way for the next file.
test.beforeEach(async ({ request }) => {
  await reseed(request);
});

test.afterAll(async ({ request }) => {
  await reseed(request);
});

test("Birds is grouped by day", async ({ page }) => {
  await page.goto("/birds");
  await expect(page.getByRole("heading", { name: "Birds", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Today", level: 2 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Yesterday", level: 2 })).toBeVisible();
  await expect(page.getByRole("link", { name: /Nuthatch/ })).toBeVisible();
});

test("Other lists the squirrel, and the old Other animals link opens Other", async ({ page }) => {
  await page.goto("/other-animals");
  await expect(page.getByRole("heading", { name: "Other", level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: /Red squirrel/ })).toBeVisible();
});

test("Other shows the dog and the empty clip", async ({ page }) => {
  await page.goto("/other");
  await expect(page.getByRole("link", { name: /Dog/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Empty clip/ })).toBeVisible();
});

test("a favourite shows up in Favourites", async ({ page }) => {
  await page.goto("/favourites");
  await expect(page.getByText(/No favourites yet/)).toBeVisible();
  await page.goto("/birds");
  await page.getByRole("link", { name: /Blue tit/ }).first().click();
  await page.getByRole("button", { name: "Favourite", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Added to Favourites" })).toBeVisible();
  await page.goto("/favourites");
  await expect(page.getByRole("link", { name: /Blue tit/ })).toHaveCount(1);
  await expect(page.getByText(/No favourites yet/)).toBeHidden();
});

test("Back from a visit keeps your place in Birds", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 700 });
  await page.goto("/birds");
  await expect(page.getByRole("link", { name: /Nuthatch/ })).toBeVisible();
  await page.evaluate(() => window.scrollBy(0, 900)); // mobile WebKit has no mouse wheel
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(500);
  const before = await page.evaluate(() => window.scrollY);
  const cards = page.locator("main a.card");
  const index = await cards.evaluateAll((els) =>
    els.findIndex((el) => {
      const r = el.getBoundingClientRect();
      return r.top >= 0 && r.bottom <= window.innerHeight - 100; // clear of the bottom menu
    }),
  );
  expect(index).toBeGreaterThanOrEqual(0);
  await cards.nth(index).click();
  await expect(page.getByRole("button", { name: "Back" })).toBeVisible();
  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("heading", { name: "Birds", level: 1 })).toBeVisible();
  await expect.poll(() => page.evaluate((y) => Math.abs(window.scrollY - y), before)).toBeLessThan(40);
});
