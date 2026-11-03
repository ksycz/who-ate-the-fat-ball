import { describe, expect, it } from "vitest";
import source from "../public/sw.js?raw";

// sw.js is a classic script (no exports), so load its source and pull shouldCache out of it.
const policy = new Function("self", `${source}\nreturn { shouldCache, shouldCachePage };`)({
  addEventListener() {},
  location: { origin: "http://gallery.local" },
}) as { shouldCache: (url: string) => boolean; shouldCachePage: (url: string, res: Response) => boolean };
const { shouldCache, shouldCachePage } = policy;

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

describe("service worker page loads", () => {
  const html = (init: ResponseInit = {}) =>
    new Response("<!doctype html>", { status: 200, headers: { "content-type": "text/html; charset=utf-8" }, ...init });

  it("keeps a good HTML page", () => {
    expect(shouldCachePage(`${ORIGIN}/`, html())).toBe(true);
    expect(shouldCachePage(`${ORIGIN}/visit/3`, html())).toBe(true);
  });

  it("does not keep errors or anything that is not HTML", () => {
    expect(shouldCachePage(`${ORIGIN}/visit/3`, html({ status: 404 }))).toBe(false);
    expect(shouldCachePage(`${ORIGIN}/visit/3`, new Response("{}", { headers: { "content-type": "application/json" } }))).toBe(false);
    expect(shouldCachePage(`${ORIGIN}/visit/3`, new Response("x"))).toBe(false);
  });

  it("never keeps the API or media, even opened as a page", () => {
    expect(shouldCachePage(`${ORIGIN}/api/today`, html())).toBe(false);
    expect(shouldCachePage(`${ORIGIN}/media/a.mp4`, html())).toBe(false);
    expect(shouldCachePage("https://example.com/", html())).toBe(false);
  });

  it("checks for /api and /media in one place", () => {
    expect(source.match(/"\/api\/"/g)).toHaveLength(1);
    expect(source.match(/"\/media\/"/g)).toHaveLength(1);
  });
});
