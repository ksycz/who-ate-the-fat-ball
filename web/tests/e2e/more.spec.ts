import { expect, test } from "./helpers";

// More is a phone-only page, so every project looks at it at phone size.
test.use({ viewport: { width: 390, height: 844 } });

test("More → Other animals → back returns to More", async ({ page }) => {
  await page.goto("/more");
  await expect(page.getByRole("heading", { name: "More" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Favourites/ })).toBeVisible();
  await page.getByRole("link", { name: /Other animals/ }).click();
  await expect(page.getByRole("heading", { name: "Other animals", level: 1 })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "More" })).toBeVisible();
});

test("More → App status shows when the camera was seen", async ({ page }) => {
  await page.goto("/more");
  const row = page.getByRole("link", { name: /App status/ });
  await expect(row).toContainText("Camera seen 2 min ago");
  await row.click();
  await expect(page.getByRole("heading", { name: "App status" })).toBeVisible();
  await expect(page.getByText("Last seen: 09:58")).toBeVisible();
  await expect(page.getByText("Reachable")).toBeVisible();
});
