/* CoachHub Hockey — service worker.
   Caches ONLY non-sensitive static assets + an offline fallback page.
   Authenticated HTML, POSTs and dynamic team data are never cached. */
'use strict';

var CACHE = 'coachhub-v3';
var OFFLINE_URL = '/static/offline.html';
var PRECACHE = [
  OFFLINE_URL,
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/manifest.webmanifest'
];

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
        if (k !== CACHE) { return caches.delete(k); }   // drop old versions
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  // Never touch non-GET (POST etc.) — let the network handle it.
  if (req.method !== 'GET') { return; }

  var url;
  try { url = new URL(req.url); } catch (e) { return; }
  // Same-origin only (skip Google Fonts and any cross-origin).
  if (url.origin !== self.location.origin) { return; }

  // Navigations (HTML documents): network-first, fall back to offline page.
  // The response is NOT cached, so authenticated/team-specific HTML never persists.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(function () {
        return caches.match(OFFLINE_URL);
      })
    );
    return;
  }

  // Static assets only: cache-first, keyed by path (ignores the ?v= cache-buster
  // so each asset is stored once). Everything else falls through to the network
  // untouched (no caching of dynamic same-origin data).
  if (url.pathname.indexOf('/static/') === 0) {
    var key = url.origin + url.pathname;
    event.respondWith(
      caches.open(CACHE).then(function (cache) {
        return cache.match(key).then(function (hit) {
          if (hit) { return hit; }
          return fetch(req).then(function (resp) {
            if (resp && resp.status === 200 && resp.type === 'basic') {
              cache.put(key, resp.clone());
            }
            return resp;
          });
        });
      })
    );
  }
});
