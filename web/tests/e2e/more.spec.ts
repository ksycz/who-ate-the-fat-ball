import { expect, reseed, test } from "./helpers";

// Playing a visit marks it watched (and clears the New species banner), so start from the seeded day, whatever ran before.
test.beforeEach(async ({ request }) => {
  await reseed(request);
});

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

test("Unlock editing → a correct PIN returns to More", async ({ page }) => {
  // The test service treats this browser as the Mac, so pretend it is a phone that may not edit yet.
  let unlocked = false;
  await page.route("**/api/me", (route) => route.fulfill({ json: { can_edit: unlocked } }));
  await page.route("**/api/unlock", (route) => {
    unlocked = true;
    return route.fulfill({ json: { ok: true } });
  });
  await page.goto("/more");
  await page.getByRole("link", { name: "Unlock editing" }).click();
  await expect(page.getByRole("heading", { name: "Unlock editing" })).toBeVisible();
  await page.getByLabel("Edit PIN").fill("1234");
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(page).toHaveURL(/\/more$/);
  await expect(page.getByRole("heading", { name: "More" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Unlock editing" })).toHaveCount(0);
});

test("Unlock editing → a wrong PIN says so and stays on Unlock", async ({ page }) => {
  // The real PIN check (hashing, lockout) is covered by the API tests; here only the page's reaction to a 401.
  await page.route("**/api/me", (route) => route.fulfill({ json: { can_edit: false } }));
  await page.route("**/api/unlock", (route) => route.fulfill({ status: 401, json: { detail: "wrong_pin" } }));
  await page.goto("/more");
  await page.getByRole("link", { name: "Unlock editing" }).click();
  await page.getByLabel("Edit PIN").fill("0000");
  await page.getByRole("button", { name: "Unlock", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("That PIN isn't right");
  await expect(page).toHaveURL(/\/unlock$/);
});
