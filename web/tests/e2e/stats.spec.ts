import { BUSY, expect, isPhone, reseed, test } from "./helpers";

// Playing a visit marks it watched (and clears the New species banner), so start from the seeded day, whatever ran before.
test.beforeEach(async ({ request }) => {
  await reseed(request);
});

interface Summary {
  slots: string[];
  heatmap: { day: string; cells: number[] }[];
}

// The busiest single cell, found from the API rather than assumed.
async function busiestCell(request: import("@playwright/test").APIRequestContext) {
  const s = (await (await request.get(`${BUSY}/api/stats?weeks=4`)).json()) as Summary;
  let best = { day: "", slot: "", n: -1 };
  for (const row of s.heatmap)
    row.cells.forEach((n, i) => {
      if (n > best.n) best = { day: row.day, slot: s.slots[i], n };
    });
  return `${best.day} ${best.slot} · ${best.n} ${best.n === 1 ? "visit" : "visits"}`;
}

test("tapping the busiest heatmap cell shows its value", async ({ page, request }) => {
  const text = await busiestCell(request);
  await page.goto("/stats");
  await expect(page.getByRole("heading", { name: "Stats", level: 1 })).toBeVisible();
  const status = page.getByRole("status").filter({ hasText: /Tap a square|visit/ });
  await expect(status).toHaveText("Tap a square to see the number of visits");
  await page.getByRole("button", { name: text, exact: true }).click();
  await expect(status).toHaveText(text);
  await expect(page.getByRole("button", { name: text, exact: true })).toHaveAttribute("aria-pressed", "true");
});

test("the phone bar has five tabs and the heatmap fits 390 px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/stats");
  const nav = page.getByRole("navigation", { name: "Main" }).filter({ visible: true });
  await expect(nav.getByRole("link")).toHaveText(["Today", "Videos", "Birds", "Stats", "More"]);
  await expect(nav.getByRole("link", { name: "Stats" })).toHaveAttribute("aria-current", "page");
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits).toBe(true);
});

test("Stats sits above App status in the side menu", async ({ page }) => {
  test.skip(isPhone(page), "the side menu is for big screens");
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" }).filter({ visible: true });
  await nav.getByRole("link", { name: "Stats" }).click();
  await expect(page).toHaveURL(/\/stats$/);
  const labels = await nav.getByRole("link").allTextContents();
  const i = labels.findIndex((l) => l.trim() === "Stats");
  expect(labels[i + 1]).toContain("App status");
});
