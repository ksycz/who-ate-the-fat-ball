import { test as base, expect, type APIRequestContext, type Page } from "@playwright/test";

// The service and the browser both think it is 2026-11-02 10:00.
export const NOW = "2026-11-02T10:00:00";
export const BUSY = "http://127.0.0.1:8765";
export const QUIET = "http://127.0.0.1:8766";
export const PROBLEM = "http://127.0.0.1:8767";

export const test = base.extend({
  page: async ({ page }, use) => {
    await page.clock.setFixedTime(NOW);
    await use(page);
  },
});
export { expect };

// Put the busy day back as it was seeded (for specs that change data).
export async function reseed(request: APIRequestContext, origin = BUSY): Promise<void> {
  const res = await request.post(`${origin}/__e2e/reseed`);
  expect(res.status()).toBe(204);
}

// The id of the first visit on a list, newest first.
export async function firstVisitId(request: APIRequestContext, query = "category=birds"): Promise<number> {
  const res = await request.get(`${BUSY}/api/visits?${query}&limit=1`);
  return (await res.json()).items[0].id;
}

export const isPhone = (page: Page) => (page.viewportSize()?.width ?? 0) < 768;
