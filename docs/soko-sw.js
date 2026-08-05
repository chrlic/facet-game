const CACHE = "soko-v6";
// SOKO-SENSEI installs as its own PWA (scope "./soko-sensei.html"). Offline-capable for the
// vs-AI game: network-first, fall back to cache. Online multiplayer needs the network (/api/).
const ASSETS = [
  "./soko-sensei.html", "./glyph_engine.js", "./adapter.js", "./vue.global.prod.js",
  "./manifest-soko.json", "./soko-icon-192.png", "./soko-icon-512.png", "./soko-favicon.png"
];

self.addEventListener("install", e => {
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
  if (e.request.method !== "GET") return;
  if (e.request.url.includes("/api/")) return;   // never cache API calls (multiplayer/account are live)
  e.respondWith(
    fetch(e.request).then(r => {
      if (r && r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); }
      return r;
    }).catch(() => caches.match(e.request))
  );
});
