import { expect, isPhone, reseed, test } from "./helpers";

// These specs change data: start each one from the seeded day, and leave it that way for the next file.
test.beforeEach(async ({ request }) => {
  await reseed(request);
});

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

test("Next and Previous go through the list the visit was opened from", async ({ page }) => {
  await page.goto("/birds/species");
  await page.getByRole("link", { name: /Blue tit/ }).click();
  await page.getByRole("link", { name: /Blue tit/ }).first().click();
  await expect(page.getByRole("heading", { name: "Blue tit", level: 1 })).toBeVisible();
  const next = page.getByRole("button", { name: "Next" });
  await expect(next).toBeEnabled();
  await next.click();
  await expect(page).toHaveURL(/\/visit\/\d+\?list=/);
  await expect(page.getByRole("heading", { name: "Blue tit", level: 1 })).toBeVisible();
  await expect(next).toBeDisabled(); // only blue tits in this list: the older visits are great tits
  await page.getByRole("button", { name: "Previous" }).click();
  await expect(next).toBeEnabled();
});

test("a clip that ends plays on to the next visit, and Back returns to the list", async ({ page }) => {
  await page.goto("/birds");
  await page.locator("a.card").first().click();
  await expect(page.getByRole("button", { name: "Next" })).toBeEnabled();
  const first = page.url();
  // Past the last clip of this visit, as when it finishes playing.
  for (let i = 0; i < 3 && page.url() === first; i++) {
    await page.locator("video").evaluate((v) => v.dispatchEvent(new Event("ended")));
    await page.waitForTimeout(100);
  }
  await expect(page).not.toHaveURL(first);
  await page.getByRole("button", { name: "Back" }).click();
  await expect(page).toHaveURL(/\/birds$/);
});

test("arrow keys move between visits", async ({ page }) => {
  await page.goto("/birds");
  await page.locator("a.card").first().click();
  await expect(page.getByRole("button", { name: "Next" })).toBeEnabled();
  const first = page.url();
  await page.keyboard.press("ArrowRight");
  await expect(page).not.toHaveURL(first);
  await expect(page.getByRole("button", { name: "Previous" })).toBeEnabled();
  await page.keyboard.press("ArrowLeft");
  await expect(page).toHaveURL(first);
});
