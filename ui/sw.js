// Keeps the phone app's own files on the phone, so it still opens (and says "laptop offline")
// when the laptop is asleep. Jarvis's answers and data are never cached.
const CACHE = "jarvis-shell-v3";
const SHELL = ["/m", "/mobile.css", "/mobile.js", "/orb.js", "/manifest.json", "/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api") || url.pathname === "/events" || url.pathname === "/pair") return;
  const key = url.pathname === "/" ? "/m" : url.pathname;
  if (!SHELL.includes(key)) return;
  // network first (so updates arrive), the saved copy when the laptop can't be reached
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(key, copy)); }
    return r;
  }).catch(() => caches.match(key)));
});
