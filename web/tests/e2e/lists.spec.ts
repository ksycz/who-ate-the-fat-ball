import { expect, reseed, test } from "./helpers";

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

test("Other animals lists the squirrel", async ({ page }) => {
  await page.goto("/other-animals");
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
