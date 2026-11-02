// Caches only the app shell (the page, /assets/*, icons). /api/* and /media/* always go to the network,
// so data is never stale. shouldCache is the whole policy; web/tests/sw.test.ts loads this file to test it.
const CACHE = "fatball-shell-v1";
const SHELL_FILES = ["/favicon.svg", "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"];

function shouldCache(url) {
  const u = new URL(url, self.location.origin);
  if (u.origin !== self.location.origin) return false;
  const p = u.pathname;
  if (p.startsWith("/api/") || p.startsWith("/media/")) return false;
  return p === "/" || p.startsWith("/assets/") || SHELL_FILES.includes(p);
}

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/", ...SHELL_FILES])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

// Network first, falling back to the cached copy when offline; cacheable responses refresh the cache.
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const navigation = req.mode === "navigate";
  if (!navigation && !shouldCache(req.url)) return;
  if (navigation && new URL(req.url).pathname.match(/^\/(api|media)\//)) return;
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && shouldCache(navigation ? "/" : req.url)) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(navigation ? "/" : req, copy));
        }
        return res;
      })
      .catch(() => caches.match(navigation ? "/" : req).then((hit) => hit || Response.error())),
  );
});
