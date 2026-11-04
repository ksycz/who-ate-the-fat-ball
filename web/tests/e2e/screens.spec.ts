import type { APIRequestContext, Locator, Page } from "@playwright/test";
import { expect, firstVisitId, reseed, test } from "./helpers";

// Screenshots of the main screens over the synthetic e2e seed (generated test-pattern clips, never real
// footage). They run in the chromium project only: fonts and anti-aliasing differ between engines.
test.beforeEach(async ({ request }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium", "screenshots are taken in chromium only");
  await reseed(request); // playing a visit marks it watched, which would change the next picture
});

test.afterAll(async ({ request }) => {
  await reseed(request);
});

// Wait until every picture on the page has loaded, and the web font is ready.
async function settled(page: Page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      [...document.images].map((img) => (img.complete ? undefined : new Promise((r) => { img.onload = img.onerror = r; }))),
    );
  });
}

// The <video> shows a moving test pattern (hidden with CSS in shot(), not masked, so the overlays on it stay in the picture), the camera line counts minutes and App status shows this Mac's free disk space: mask those two texts.
const masks = (page: Page): Locator[] => [page.getByText(/Camera seen|Camera not seen|min ago|GB free/)];

async function shot(page: Page, name: string) {
  await settled(page);
  await page.addStyleTag({ content: "video { visibility: hidden !important; }" });
  await expect(page).toHaveScreenshot(name, {
    animations: "disabled",
    mask: masks(page),
    maxDiffPixelRatio: 0.02,
  });
}

const GREAT_TIT = "category=birds&species=Parus%20major";

const screens: [string, (page: Page, request: APIRequestContext) => Promise<void>][] = [
  ["today", async (page) => {
    await page.goto("/");
    await expect(page.getByText("Checking who it is…")).toBeVisible();
  }],
  ["birds", async (page) => {
    await page.goto("/birds");
    await expect(page.getByRole("heading", { name: "Yesterday", level: 2 })).toBeVisible();
  }],
  ["by-species", async (page) => {
    await page.goto("/birds/species");
    await expect(page.getByRole("link", { name: /Great tit/ })).toBeVisible();
  }],
  ["visit", async (page, request) => {
    await page.goto(`/visit/${await firstVisitId(request, GREAT_TIT)}`);
    await expect(page.getByRole("button", { name: "Not right? Change" })).toBeVisible();
  }],
  ["videos", async (page) => {
    await page.goto("/videos");
    await expect(page.getByText(/^1 of \d+/)).toBeVisible();
  }],
  ["stats", async (page) => {
    await page.goto("/stats");
    await expect(page.getByRole("heading", { name: "Stats", level: 1 })).toBeVisible();
  }],
  ["status", async (page) => {
    await page.goto("/status");
    await expect(page.getByText("Last seen: 09:58")).toBeVisible();
  }],
];

test.describe("desktop 1280x800", () => {
  test.use({ viewport: { width: 1280, height: 800 } });
  for (const [name, open] of screens) {
    test(name, async ({ page, request }) => {
      await open(page, request);
      await shot(page, `${name}-1280.png`);
    });
  }
});

test.describe("phone 390x844", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  for (const [name, open] of screens) {
    test(name, async ({ page, request }) => {
      await open(page, request);
      await shot(page, `${name}-390.png`);
    });
  }

  test("more", async ({ page }) => {
    await page.goto("/more");
    await expect(page.getByRole("link", { name: /App status/ })).toContainText("Camera seen");
    await shot(page, "more-390.png");
  });
});
