const CACHE = "octachess-v1";
// OCTA-CHESS installs as its own PWA (scope "./octa-chess.html"). Offline-capable:
// network-first, fall back to cache. The game is fully client-side (no /api/).
const ASSETS = [
  "./octa-chess.html", "./octachess_engine.js", "./adapter.js", "./vue.global.prod.js",
  "./manifest-octa-chess.json", "./ocx-icon-192.png", "./ocx-icon-512.png", "./ocx-favicon.png"
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
  e.respondWith(
    fetch(e.request).then(r => {
      if (r && r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); }
      return r;
    }).catch(() => caches.match(e.request))
  );
});
