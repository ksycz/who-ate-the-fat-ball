import { expect, isPhone, reseed, test } from "./helpers";

// These specs change data: start each one from the seeded day, and leave it that way for the next file.
test.beforeEach(async ({ request }) => {
  await reseed(request);
});

test.afterAll(async ({ request }) => {
  await reseed(request);
});

// The nav holds a link to Videos on both layouts; on the phone only the bottom bar shows.
async function openVideos(page: import("@playwright/test").Page) {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" }).filter({ visible: true });
  await nav.getByRole("link", { name: "Videos" }).click();
  await expect(page).toHaveURL(/\/videos$/);
  await expect(page.getByRole("heading", { name: "Videos" })).toBeVisible();
}

test("the Videos picker is used without leaving the feed", async ({ page, request }) => {
  const total = (await (await request.get("http://127.0.0.1:8765/api/videos?limit=1")).json()).total as number;
  await openVideos(page);
  await expect(page.getByText(`1 of ${total}`)).toBeVisible();
  await expect(page.locator("video")).toHaveCount(1);

  await page.getByRole("button", { name: "Next clip" }).click();
  await expect(page.getByText(`2 of ${total}`)).toBeVisible();

  await page.getByRole("button", { name: "What is it?" }).click();
  const dialog = page.getByRole("dialog", { name: "What is it?" });
  await dialog.getByRole("button", { name: /^Blue tit/ }).click();
  const toast = page.getByRole("status").filter({ hasText: "Changed to Blue tit" });
  await expect(toast).toBeVisible();
  await expect(page).toHaveURL(/\/videos$/);
  await expect(page.getByText(`2 of ${total}`)).toBeVisible();
  await expect(page.getByText("corrected by you")).toBeVisible();

  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(toast).toBeHidden();
  await expect(page.getByText("corrected by you")).toBeHidden();
  await expect(page.getByText(`2 of ${total}`)).toBeVisible();
});

test("a chip narrows the feed and a swipe or Previous goes back", async ({ page }) => {
  await openVideos(page);
  await page.getByRole("button", { name: "Blue tit" }).click();
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Previous" })).toBeDisabled();
  await page.getByRole("button", { name: "Next clip" }).click();
  await expect(page.getByText(/^2 of \d+$/)).toBeVisible();
  await page.getByRole("button", { name: "Previous" }).click();
  await expect(page.getByText(/^1 of \d+$/)).toBeVisible();
  if (!isPhone(page)) {
    await page.keyboard.press("ArrowRight");
    await expect(page.getByText(/^2 of \d+$/)).toBeVisible();
  }
});

test("the video controls are not covered by the overlays", async ({ page }) => {
  await openVideos(page);
  await expect(page.locator("video")).toBeVisible();
  const covered = await page.evaluate(() => {
    const v = document.querySelector("video") as HTMLVideoElement;
    const r = v.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.bottom - 10);
    return hit === v ? null : (hit?.outerHTML.slice(0, 80) ?? "nothing");
  });
  expect(covered).toBeNull();
});
