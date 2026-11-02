import { expect, isPhone, reseed, test } from "./helpers";

test.afterAll(async ({ request }) => {
  await reseed(request);
});

test("open a visit, play it, and the playing mark moves", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /Great tit/ }).filter({ hasText: "2 clips" }).click();
  await expect(page.getByRole("heading", { name: "Great tit" })).toBeVisible();
  await expect(page.locator("video")).toBeVisible();
  await expect(page.getByText("2 clips in this visit")).toBeVisible();
  const first = page.getByRole("button", { name: /^Clip 1,/ });
  const second = page.getByRole("button", { name: /^Clip 2,/ });
  await expect(first).toHaveAccessibleName(/playing/);
  await expect(second).not.toHaveAccessibleName(/playing/);
  await second.click();
  await expect(second).toHaveAccessibleName(/playing/);
  await expect(first).not.toHaveAccessibleName(/playing/);
});

test("correct the species with the picker, then Undo", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /Great tit/ }).filter({ hasText: "1 clip" }).first().click();
  await expect(page.getByRole("heading", { name: "Great tit" })).toBeVisible();
  await page.getByRole("button", { name: "Not right? Change" }).click();
  const dialog = page.getByRole("dialog", { name: "What is it?" });
  await expect(dialog.getByText("Birds seen at your feeder")).toBeVisible();
  await dialog.getByRole("button", { name: /^Blue tit/ }).click();
  const toast = page.getByRole("status").filter({ hasText: "Changed to Blue tit" });
  await expect(toast).toBeVisible();
  await expect(page.getByRole("heading", { name: "Blue tit" })).toBeVisible();
  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByRole("heading", { name: "Great tit" })).toBeVisible();
  await expect(toast).toBeHidden();
});

test("Nothing moves the visit to Other, and Undo brings it back", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /Great tit/ }).filter({ hasText: "1 clip" }).first().click();
  await page.getByRole("button", { name: "Not right? Change" }).click();
  const dialog = page.getByRole("dialog", { name: "What is it?" });
  await expect(dialog.getByText("Not a bird?")).toBeVisible();
  await dialog.getByRole("button", { name: /Nothing/ }).click();
  const toast = page.getByRole("status").filter({ hasText: "Moved to Other" });
  await expect(toast).toBeVisible();
  await expect(page.getByRole("heading", { name: "Empty clip" })).toBeVisible();
  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByRole("heading", { name: "Great tit" })).toBeVisible();
});

test("watching the new species clears the banner", async ({ page }) => {
  await page.goto(isPhone(page) ? "/" : "/birds");
  await page.getByRole("link", { name: "Watch" }).click();
  await expect(page.getByRole("heading", { name: "Nuthatch" })).toBeVisible();
  const video = page.locator("video");
  await expect(video).toBeVisible();
  const watched = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith("/watched"));
  await video.evaluate((v: HTMLVideoElement) => v.play().catch(() => undefined));
  await watched;
  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("heading", { name: isPhone(page) ? "Today" : "Birds", level: 1 })).toBeVisible();
  await expect(page.getByRole("link", { name: /Great tit/ }).first()).toBeVisible();
  await expect(page.getByText("New species")).toBeHidden();
});
