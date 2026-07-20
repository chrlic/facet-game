const CACHE = "hyperscale-v3";
const ASSETS = [
  "./hyperscale.html",
  "./hyperscale_engine.js",
  "./adapter.js",
  "./vue.global.prod.js",
  "./manifest-hyperscale.json",
  "./hs-icon-192.png",
  "./hs-icon-512.png",
  "./hs-favicon.png"
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

// Network-first with cache fallback: fresh code when online, full offline play
// from cache when the network is gone. API calls bypass the cache.
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
