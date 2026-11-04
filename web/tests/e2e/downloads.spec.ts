import { statSync } from "node:fs";
import { expect, firstVisitId, isPhone, reseed, test } from "./helpers";

// Opening a visit plays it, which marks it watched; start each spec from the seeded day.
test.beforeEach(async ({ request }) => {
  await reseed(request);
});

test.afterAll(async ({ request }) => {
  await reseed(request);
});

test("Download ▾ → Photo gives a .jpg", async ({ page, request }) => {
  await page.goto(`/visit/${await firstVisitId(request)}`);
  await page.getByRole("button", { name: /^Download/ }).click();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Photo (.jpg)" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.jpg$/);
});

test("Download this day (.zip) → confirm gives fat-ball-2026-11-02.zip of the size announced", async ({ page }) => {
  test.skip(isPhone(page), "the day .zip button is for big screens");
  await page.setViewportSize({ width: 1280, height: 800 });
  const plan = page.waitForResponse((r) => r.url().endsWith("/api/downloads/zip") && r.request().method() === "POST");
  await page.goto("/birds");
  await expect(page.getByRole("heading", { name: "Today", level: 2 })).toBeVisible();
  await page.getByRole("button", { name: "Download this day (.zip)" }).first().click();
  const sizeBytes = ((await (await plan).json()) as { size_bytes: number }).size_bytes;
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/^Download 8 visits \(/)).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    dialog.getByRole("button", { name: "Download", exact: true }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("fat-ball-2026-11-02.zip");
  const saved = await download.path();
  expect(Math.abs(statSync(saved).size - sizeBytes) / sizeBytes).toBeLessThan(0.05);
});

test("Download this day (.zip) is not shown at phone width", async ({ page }) => {
  await page.setViewportSize({ width: 412, height: 915 });
  await page.goto("/birds");
  await expect(page.getByRole("heading", { name: "Today", level: 2 })).toBeVisible();
  await expect(page.getByRole("button", { name: "Download this day (.zip)" })).toHaveCount(0);
});
