import { expect, isPhone, PROBLEM, QUIET, test } from "./helpers";

test("a busy day: champion, new species, checking and failed clips", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
  const champion = page.locator(".champion");
  await expect(champion).toContainText(/Today.s fat-ball champion/);
  await expect(champion).toContainText("Great tit");
  await expect(champion).toContainText("4 visits");
  await expect(page.getByText("8 visits · 3 species")).toBeVisible();

  // The phone shows the banner on Today; the side layout shows it on Birds instead.
  if (!isPhone(page)) await page.goto("/birds");
  const banner = page.getByText("New species").locator("xpath=ancestor::div[@role='status']");
  await expect(banner).toContainText("New species");
  await expect(banner).toContainText("Nuthatch · 09:45");
  await expect(banner.getByRole("link", { name: "Watch" })).toBeVisible();

  await page.goto("/");
  await expect(page.getByText("Checking who it is…")).toBeVisible();
  await expect(page.getByText(/1 clip couldn.t be fetched/)).toBeVisible();
});

test("a quiet day says so and points to yesterday", async ({ page }) => {
  await page.goto(`${QUIET}/`);
  await expect(page.getByText("Quiet so far")).toBeVisible();
  await expect(page.getByText(/No visitors yet today\. Last visitor: Blue tit, yesterday 17:40/)).toBeVisible();
  await expect(page.getByText("The camera was last seen at 09:58.")).toBeVisible();
  await expect(page.getByText("Camera seen 2 min ago").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /See yesterday.s visits/ })).toBeVisible();
});

test("a camera problem shows a notice that leads to App status", async ({ page }) => {
  await page.goto(`${PROBLEM}/`);
  const notice = page.getByRole("link", { name: /Camera not seen since yesterday 18:40/ });
  await expect(notice).toContainText("It may need charging");
  await notice.click();
  await expect(page.getByRole("heading", { name: "App status" })).toBeVisible();
  await expect(page.getByText("Not reachable")).toBeVisible();
});
