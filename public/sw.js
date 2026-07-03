// Service worker: cache the app shell for offline launch.
// Relative URLs so it works whether served from the domain root (local) or a
// project subpath (GitHub Pages). Bump CACHE on any shell change.
const CACHE = "health-dashboard-v4";
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
