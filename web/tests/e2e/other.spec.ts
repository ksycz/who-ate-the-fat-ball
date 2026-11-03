import { expect, isPhone, reseed, test } from "./helpers";

// Deleting changes data: start each spec from the seeded day, and leave it that way for the next file.
test.beforeEach(async ({ request }) => {
  await reseed(request);
});

test.afterAll(async ({ request }) => {
  await reseed(request);
});

test("Only dogs shows the dog and not the empty clip", async ({ page }) => {
  await page.goto("/other");
  await page.getByRole("group", { name: "Show" }).getByRole("button", { name: "Only dogs" }).click();
  await expect(page.getByRole("link", { name: /Dog/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Empty clip/ })).toHaveCount(0);
});

test("Empty clips: Select all, Delete, confirm", async ({ page }) => {
  await page.goto("/other");
  await page.getByRole("group", { name: "Show" }).getByRole("button", { name: "Empty clips" }).click();
  await expect(page.getByRole("link", { name: /Empty clip/ })).toHaveCount(1);
  await expect(page.getByRole("link", { name: /Dog/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("button", { name: "Select all" }).click();
  await page.getByRole("region", { name: "Selected visits" }).getByRole("button", { name: "Delete", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Delete 1 empty clip? This can't be undone.")).toBeVisible();
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "1 empty clip deleted" })).toBeVisible();
  await expect(page.getByText("No empty clips")).toBeVisible();
  // The dog is still there.
  await page.getByRole("group", { name: "Show" }).getByRole("button", { name: "Only dogs" }).click();
  await expect(page.getByRole("link", { name: /Dog/ })).toBeVisible();
});

test("the same on a phone-sized screen", async ({ page }) => {
  await page.setViewportSize({ width: 412, height: 915 });
  expect(isPhone(page)).toBe(true);
  await page.goto("/other");
  await page.getByRole("group", { name: "Show" }).getByRole("button", { name: "Empty clips" }).click();
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("button", { name: "Select all" }).click();
  await page.getByRole("region", { name: "Selected visits" }).getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "1 empty clip deleted" })).toBeVisible();
  await expect(page.getByText("No empty clips")).toBeVisible();
});
