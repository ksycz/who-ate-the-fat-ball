import { expect, reseed, test } from "./helpers";

// HTML5 drag and drop needs a desktop mouse; the iPad and phone projects use the Move buttons instead.
test.beforeEach(({}, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "HTML5 drag needs a desktop mouse");
});
test.use({ viewport: { width: 1280, height: 800 } });

test.beforeEach(async ({ request }) => {
  await reseed(request);
});
test.afterAll(async ({ request }) => {
  await reseed(request);
});

const sortedCount = async (request: import("@playwright/test").APIRequestContext, key: string) =>
  ((await (await request.get("/api/status")).json()).sorted as Record<string, number>)[key];

// Editing is open on the Mac itself; skip if the service says otherwise.
async function unlocked(page: import("@playwright/test").Page) {
  await page.goto("/birds");
  await expect(page.getByRole("button", { name: /^More actions for / }).first()).toBeVisible();
}

test("drag a Birds card onto Other animals in the side menu", async ({ page, request }) => {
  const before = await sortedCount(request, "other_animals");
  await unlocked(page);
  const card = page.locator("a.card").first();
  await card.dragTo(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /^Other animals/ }));
  const toast = page.getByRole("status").filter({ hasText: /moved to Other animals/ });
  await expect(toast).toBeVisible();
  await expect(toast.getByRole("button", { name: "Undo" })).toBeVisible();
  await expect.poll(() => sortedCount(request, "other_animals")).toBe(before + 1);
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /^Other animals/ })).toContainText(String(before + 1));
});

test("the same move with the keyboard: Tab to ⋯, Enter, ArrowDown, Enter", async ({ page, request }) => {
  const before = await sortedCount(request, "other");
  await unlocked(page);
  const more = page.getByRole("button", { name: /^More actions for / }).first();
  await more.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu")).toBeVisible();
  await page.keyboard.press("ArrowDown"); // Other animals -> Other
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status").filter({ hasText: /moved to Other(?! animals)/ })).toBeVisible();
  await expect.poll(() => sortedCount(request, "other")).toBe(before + 1);
});
