const CACHE = "facet-v2";
const ASSETS = [
  "./",
  "./index.html",
  "./vue.global.prod.js",
  "./facet_engine.js",
  "./adapter.js",
  "./manifest.json",
  "./icon-192.png",
  "./icon-512.png",
  "./favicon.png"
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Network-first with cache fallback: fresh code whenever online (so local
// development and new deploys are never stuck on stale assets), full offline
// play from cache when the network is gone. API calls bypass the cache.
self.addEventListener("fetch", e => {
  if (e.request.url.includes("/api/")) return;
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request).then(r => {
      if (r && r.ok) {
        const copy = r.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
      }
      return r;
    }).catch(() => caches.match(e.request))
  );
});
