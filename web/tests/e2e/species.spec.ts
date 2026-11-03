import { expect, isPhone, test, BUSY } from "./helpers";

const GREAT = "Parus major";

async function greatTitWeek(request: import("@playwright/test").APIRequestContext) {
  const res = await request.get(`${BUSY}/api/species?period=week`);
  const rows: { scientific: string; visits: number }[] = await res.json();
  return rows.find((r) => r.scientific === GREAT)!.visits;
}

test("Birds → By species → Great tit's visits → Back", async ({ page, request }) => {
  const visits = await greatTitWeek(request);
  await page.goto("/birds");
  const view = page.getByRole("group", { name: "View" });
  await expect(view.getByRole("button", { name: "All visits" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "This week" })).toHaveCount(0);

  await view.getByRole("button", { name: "By species" }).click();
  await expect(page).toHaveURL(/\/birds\/species$/);
  await expect(page.getByRole("button", { name: "This week" })).toHaveAttribute("aria-pressed", "true");
  const card = page.getByRole("link", { name: /Great tit/ });
  await expect(card).toContainText(`${visits}`);
  await expect(card).toContainText(visits === 1 ? "visit" : "visits");
  await expect(card).toContainText("Last seen");

  await card.click();
  await expect(page).toHaveURL(/\/birds\/species\/Parus%20major$/);
  await expect(page.getByRole("heading", { name: "Great tit", level: 1 })).toBeVisible();
  const cards = page.locator("a[href^='/visit/']");
  await expect(cards.first()).toBeVisible();
  await expect(page.getByRole("link", { name: /Blue tit|Nuthatch/ })).toHaveCount(0);
  const all = await request.get(`${BUSY}/api/visits?category=birds&species=${encodeURIComponent(GREAT)}&limit=200`);
  expect(await cards.count()).toBe((await all.json()).items.length);

  await page.getByRole("button", { name: "Back" }).click();
  await expect(page).toHaveURL(/\/birds\/species$/);
  await expect(page.getByRole("link", { name: /Great tit/ })).toBeVisible();
});

test("the period chips change the counts, and All visits has none", async ({ page, request }) => {
  const res = await request.get(`${BUSY}/api/species?period=all`);
  const rows: { scientific: string; visits: number }[] = await res.json();
  const allTime = rows.find((r) => r.scientific === GREAT)!.visits;
  await page.goto("/birds/species");
  await page.getByRole("button", { name: "All time" }).click();
  await expect(page.getByRole("link", { name: /Great tit/ })).toContainText(`${allTime}`);
  await expect(page.getByText(/species · all time/)).toBeVisible();
  await page.getByRole("group", { name: "View" }).getByRole("button", { name: "All visits" }).click();
  await expect(page.getByRole("button", { name: "All time" })).toHaveCount(0);
});

test("the phone layout has the same flow", async ({ page }) => {
  await page.setViewportSize({ width: 412, height: 915 });
  expect(isPhone(page)).toBe(true);
  await page.goto("/birds/species");
  await page.getByRole("link", { name: /Great tit/ }).click();
  await expect(page.getByRole("heading", { name: "Great tit", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Back" }).click();
  await expect(page).toHaveURL(/\/birds\/species$/);
});
