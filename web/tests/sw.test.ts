import { describe, expect, it } from "vitest";
import source from "../public/sw.js?raw";

// sw.js is a classic script (no exports), so load its source and pull shouldCache out of it.
const shouldCache = new Function("self", `${source}\nreturn shouldCache;`)({
  addEventListener() {},
  location: { origin: "http://gallery.local" },
}) as (url: string) => boolean;

const ORIGIN = "http://gallery.local";

describe("service worker shouldCache", () => {
  it("never caches the API or media, so data is never stale", () => {
    expect(shouldCache(`${ORIGIN}/api/today`)).toBe(false);
    expect(shouldCache(`${ORIGIN}/api/visits?limit=50`)).toBe(false);
    expect(shouldCache(`${ORIGIN}/media/2026/11/02/a.mp4`)).toBe(false);
    expect(shouldCache(`${ORIGIN}/media/poster.jpg`)).toBe(false);
  });

  it("caches the app shell: page, built assets, icons", () => {
    expect(shouldCache(`${ORIGIN}/`)).toBe(true);
    expect(shouldCache(`${ORIGIN}/assets/index-abc.js`)).toBe(true);
    expect(shouldCache(`${ORIGIN}/icon-192.png`)).toBe(true);
    expect(shouldCache(`${ORIGIN}/favicon.svg`)).toBe(true);
  });

  it("does not cache anything else, or other origins", () => {
    expect(shouldCache(`${ORIGIN}/sw.js`)).toBe(false);
    expect(shouldCache(`${ORIGIN}/visit/3`)).toBe(false);
    expect(shouldCache("https://example.com/assets/x.js")).toBe(false);
  });
});
