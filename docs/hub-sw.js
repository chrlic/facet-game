const CACHE = "games-hub-v1";
// The hub PWA (scope "./") caches the whole suite so every game works offline
// once installed. Each game also ships its own SW for individual installs.
const ASSETS = [
  "./", "./index.html", "./manifest-hub.json", "./hub-icon-192.png", "./hub-icon-512.png", "./hub-favicon.png",
  "./vue.global.prod.js", "./adapter.js",
  "./facet.html", "./facet_engine.js", "./manifest.json", "./icon-192.png", "./icon-512.png",
  "./backbone.html", "./backbone_engine.js", "./manifest-backbone.json", "./bb-icon-192.png", "./bb-icon-512.png",
  "./hyperscale.html", "./hyperscale_engine.js", "./manifest-hyperscale.json", "./hs-icon-192.png", "./hs-icon-512.png"
];

self.addEventListener("install", e => {
  // don't fail the whole install if one asset 404s — cache what we can
  e.waitUntil(caches.open(CACHE).then(c => Promise.allSettled(ASSETS.map(a => c.add(a)))));
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
