import { expect, reseed, test } from "./helpers";

// These specs change data: start each one from the seeded day, and leave it that way for the next file.
test.beforeEach(async ({ request }) => {
  await reseed(request);
});

test.afterAll(async ({ request }) => {
  await reseed(request);
});

const sortedCount = async (request: import("@playwright/test").APIRequestContext, key: string) =>
  ((await (await request.get("/api/status")).json()).sorted as Record<string, number>)[key];

test("move two visits from Birds to Other, then Undo", async ({ page, request }) => {
  const otherBefore = await sortedCount(request, "other");
  await page.goto("/birds");
  await page.getByRole("button", { name: "Select", exact: true }).click();
  const boxes = page.getByRole("checkbox", { name: /^Select / });
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await expect(page.getByText("2 visits selected")).toBeVisible();
  await page.getByRole("button", { name: "Move to…" }).click();
  await page.getByRole("group", { name: "Move to" }).getByRole("button", { name: "Other", exact: true }).click();
  const toast = page.getByRole("status").filter({ hasText: "2 visits moved to Other" });
  await expect(toast).toBeVisible();
  await expect(page.getByText("2 visits selected")).toBeHidden();
  await expect.poll(() => sortedCount(request, "other")).toBe(otherBefore + 2);
  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(toast).toBeHidden();
  await expect.poll(() => sortedCount(request, "other")).toBe(otherBefore);
});

test("Download .zip on one selected visit downloads fat-ball-1-visits.zip", async ({ page }) => {
  await page.goto("/birds");
  await page.getByRole("button", { name: "Select", exact: true }).click();
  await page.getByRole("checkbox", { name: /^Select / }).first().check();
  await page.getByRole("button", { name: "Download .zip" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/^Download 1 visit \(/)).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    dialog.getByRole("button", { name: "Download", exact: true }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("fat-ball-1-visits.zip");
});
