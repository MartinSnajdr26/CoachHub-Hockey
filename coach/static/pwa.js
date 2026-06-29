/* CoachHub Hockey — PWA bootstrap: register the service worker and show a
   subtle, dismissible install prompt when the browser offers one. */
(function () {
  'use strict';

  // --- register service worker (root scope, served from /sw.js) ---
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () { /* non-fatal */ });
    });
  }

  // --- subtle install prompt ---
  var DISMISS_KEY = 'pwa_install_dismissed';
  function dismissed() { try { return localStorage.getItem(DISMISS_KEY) === '1'; } catch (e) { return false; } }
  function setDismissed() { try { localStorage.setItem(DISMISS_KEY, '1'); } catch (e) {} }

  var deferredPrompt = null;

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();          // we present our own button
    deferredPrompt = e;
    if (!dismissed()) { showBanner(); }
  });

  window.addEventListener('appinstalled', function () { setDismissed(); removeBanner(); });

  function removeBanner() {
    var b = document.getElementById('pwa-install'); if (b && b.parentNode) { b.parentNode.removeChild(b); }
  }

  function showBanner() {
    if (document.getElementById('pwa-install')) { return; }
    var bar = document.createElement('div');
    bar.id = 'pwa-install';
    bar.className = 'pwa-install';
    bar.setAttribute('role', 'dialog');
    bar.setAttribute('aria-label', 'Instalace aplikace');

    var label = document.createElement('span');
    label.className = 'pwa-install-text';
    label.textContent = 'Přidat CoachHub Hockey do telefonu';

    var add = document.createElement('button');
    add.type = 'button'; add.className = 'pwa-install-add'; add.textContent = 'Přidat';
    add.addEventListener('click', function () {
      if (!deferredPrompt) { removeBanner(); return; }
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then(function () { deferredPrompt = null; removeBanner(); });
    });

    var close = document.createElement('button');
    close.type = 'button'; close.className = 'pwa-install-close'; close.setAttribute('aria-label', 'Zavřít'); close.textContent = '✕';
    close.addEventListener('click', function () { setDismissed(); removeBanner(); });

    bar.appendChild(label); bar.appendChild(add); bar.appendChild(close);
    document.body.appendChild(bar);
  }
})();
