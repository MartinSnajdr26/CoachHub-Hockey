/* CoachHub Hockey — service worker.
   Caches ONLY non-sensitive static assets + an offline fallback page.
   Authenticated HTML, POSTs and dynamic team data are never cached.

   Update model (so deployed CSS/JS reach installed PWAs automatically):
   - Bump CACHE on every release; old release caches are deleted on activate.
   - Application CSS/JS use STALE-WHILE-REVALIDATE keyed by the FULL url (so a
     bumped `?v=<release>` is fetched fresh, and same-version assets are
     refreshed in the background on every load). Stable assets (icons, images,
     fonts, manifest) stay cache-first.
   - install -> skipWaiting(); activate -> clients.claim(). The page's
     registration code (pwa.js) reloads once on `controllerchange`, so a newly
     activated worker's fresh assets load without a manual reinstall. */
'use strict';

var CACHE = 'coachhub-v6';
var OFFLINE_URL = '/static/offline.html';
var PRECACHE = [
  OFFLINE_URL,
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/manifest.webmanifest'
];

// Frequently-changed application code — must never be served permanently stale.
function isAppCode(pathname) { return /\.(css|js)$/i.test(pathname); }

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) { return cache.addAll(PRECACHE); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k !== CACHE) { return caches.delete(k); }   // drop old release caches
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  // Never touch non-GET (POST etc.) — let the network handle it (no mutation caching).
  if (req.method !== 'GET') { return; }

  var url;
  try { url = new URL(req.url); } catch (e) { return; }
  // Same-origin only (skip Google Fonts and any cross-origin).
  if (url.origin !== self.location.origin) { return; }

  // Navigations (HTML documents): network-first, fall back to the offline page.
  // The response is NOT cached, so authenticated/team-specific HTML never persists.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(function () { return caches.match(OFFLINE_URL); })
    );
    return;
  }

  // Only same-origin static assets are cached; everything else (dynamic API /
  // private data) falls through to the network untouched.
  if (url.pathname.indexOf('/static/') !== 0) { return; }

  if (isAppCode(url.pathname)) {
    // Application CSS/JS: stale-while-revalidate, keyed by the FULL url so a
    // bumped `?v=<release>` becomes a fresh entry (old versions are cleared by
    // the CACHE bump on activate). Serve cached instantly; refresh in background.
    event.respondWith(
      caches.open(CACHE).then(function (cache) {
        return cache.match(url.href).then(function (hit) {
          var net = fetch(req).then(function (resp) {
            if (resp && resp.status === 200 && resp.type === 'basic') { cache.put(url.href, resp.clone()); }
            return resp;
          }).catch(function () { return hit; });   // offline -> serve cached copy
          return hit || net;                        // cached first, else network
        });
      })
    );
    return;
  }

  // Stable assets (icons, logos, images, fonts, manifest): cache-first, keyed by
  // path (query ignored — these rarely change and are safe to keep long-term).
  event.respondWith(
    caches.open(CACHE).then(function (cache) {
      var key = url.origin + url.pathname;
      return cache.match(key).then(function (hit) {
        if (hit) { return hit; }
        return fetch(req).then(function (resp) {
          if (resp && resp.status === 200 && resp.type === 'basic') { cache.put(key, resp.clone()); }
          return resp;
        });
      });
    })
  );
});
