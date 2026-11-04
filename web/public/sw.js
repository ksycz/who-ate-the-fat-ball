// Caches only the app shell (the page, /assets/*, icons). /api/* and /media/* always go to the network,
// so data is never stale. shouldCache and shouldCachePage are the whole policy; web/tests/sw.test.ts loads this file to test it.
const CACHE = "fatball-shell-v1";
const SHELL_FILES = ["/favicon.svg", "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"];

function pathOf(url) {
  const u = new URL(url, self.location.origin);
  return u.origin === self.location.origin ? u.pathname : null;
}

// The one place that keeps live data out: the API and the media are never touched.
function isData(p) {
  return p.startsWith("/api/") || p.startsWith("/media/");
}

function shouldCache(url) {
  const p = pathOf(url);
  if (p === null || isData(p)) return false;
  return p === "/" || p.startsWith("/assets/") || SHELL_FILES.includes(p);
}

// A page load is answered by the app's one HTML page, so only a good HTML reply is kept (as "/").
function isPage(url) {
  const p = pathOf(url);
  return p !== null && !isData(p);
}

function shouldCachePage(url, res) {
  return isPage(url) && res.ok && (res.headers.get("content-type") || "").includes("text/html");
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
  if (!(navigation ? isPage(req.url) : shouldCache(req.url))) return;
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (navigation ? shouldCachePage(req.url, res) : res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(navigation ? "/" : req, copy));
        }
        return res;
      })
      .catch(() => caches.match(navigation ? "/" : req).then((hit) => hit || Response.error())),
  );
});
