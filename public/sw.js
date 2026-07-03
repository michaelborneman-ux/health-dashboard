// Service worker: cache the app shell for offline launch.
// Relative URLs so it works whether served from the domain root (local) or a
// project subpath (GitHub Pages). Bump CACHE on any shell change.
const CACHE = "health-dashboard-v7";
const SHELL = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./data/garmin-data.js",
  "./data/withings-data.js",
  "./data/calories-data.js",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))),
      ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // data/*.js changes on its own schedule (each sync + push), independent of
  // app-shell deploys, so it must never go stale behind a cache-first hit.
  // Network-first with a cache fallback keeps it fresh online and available
  // offline.
  if (url.pathname.includes("/data/")) {
    // no-store: bypass the browser's own HTTP cache too, not just ours —
    // otherwise a stale disk-cached response can win even on network-first.
    event.respondWith(
      fetch(request.url, { cache: "no-store" })
        .then((resp) => {
          if (resp.ok) {
            caches.open(CACHE).then((cache) => cache.put(request, resp.clone()));
          }
          return resp;
        })
        .catch(() => caches.match(request)),
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request)
          .then((resp) => {
            if (resp.ok) {
              const copy = resp.clone();
              caches.open(CACHE).then((cache) => cache.put(request, copy));
            }
            return resp;
          })
          .catch(() => caches.match("./index.html")),
    ),
  );
});
