const CACHE = "hexago-v7";
// HEXA-GO installs as its own PWA (scope "./hexa-go.html"). Fully client-side (no /api/):
// network-first, fall back to cache for offline play.
const ASSETS = [
  "./hexa-go.html", "./hexago_engine.js", "./hexago-ai-worker.js", "./hexago_net.js", "./hexago-weights.json",
  "./adapter.js", "./vue.global.prod.js",
  "./manifest-hexa-go.json", "./hxg-icon-192.png", "./hxg-icon-512.png", "./hxg-favicon.png"
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
