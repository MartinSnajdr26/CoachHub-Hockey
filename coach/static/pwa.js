/* CoachHub Hockey — PWA bootstrap: register the service worker and show a
   subtle, dismissible install prompt when the browser offers one. */
(function () {
  'use strict';

  // --- register service worker + auto-update (root scope, served from /sw.js) ---
  if ('serviceWorker' in navigator) {
    // Reload the page EXACTLY ONCE when a newly deployed worker takes control,
    // so freshly deployed CSS/JS load without clearing site data or reinstalling.
    // `refreshing` prevents a reload loop; `hadController` skips the reload on the
    // very first install (when there was no previous controller to replace).
    var refreshing = false;
    var hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener('controllerchange', function () {
      if (refreshing) { return; }
      if (!hadController) { hadController = true; return; }  // first install: no reload
      refreshing = true;
      window.location.reload();
    });
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).then(function (reg) {
        // Proactively check for a new worker when the tab regains focus.
        if (reg && typeof reg.update === 'function') {
          document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'visible') { try { reg.update(); } catch (e) {} }
          });
        }
      }).catch(function () { /* non-fatal */ });
    });
  }

  // --- subtle install prompt ---
  var DISMISS_KEY = 'pwa_install_dismissed';
  function dismissed() { try { return localStorage.getItem(DISMISS_KEY) === '1'; } catch (e) { return false; } }
  function setDismissed() { try { localStorage.setItem(DISMISS_KEY, '1'); } catch (e) {} }

  var deferredPrompt = null;

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();          // we present our own button (never auto-open)
    deferredPrompt = e;
    // Prefer an in-page install card when the page has one (login / dashboard);
    // otherwise fall back to the subtle banner. Avoids two prompts on one page.
    if (document.querySelector('[data-pwa-install]')) { updatePwaInstallButtons(); }
    else if (!dismissed()) { showBanner(); }
  });

  window.addEventListener('appinstalled', function () {
    setDismissed(); removeBanner();
    deferredPrompt = null;
    forEachInstallControl(function (el) { setControlHidden(el, true); });   // hide inline cards too
  });

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

  // --- persistent, manual install controls: [data-pwa-install] --------------
  // Reuses the SAME deferredPrompt as the banner. Shows inline install cards on
  // the login page and dashboard; hides them when already installed / running
  // standalone; on iOS Safari (no beforeinstallprompt) shows manual "Add to
  // Home Screen" steps instead of a dead button.

  function isStandalone() {
    try {
      return (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
          || window.navigator.standalone === true;
    } catch (e) { return false; }
  }
  function isIOS() {
    var ua = navigator.userAgent || '';
    if (/iPad|iPhone|iPod/.test(ua)) { return true; }
    // iPadOS 13+ reports a desktop UA -> detect a touch-capable "Mac".
    return navigator.platform === 'MacIntel' && (navigator.maxTouchPoints || 0) > 1;
  }
  function forEachInstallControl(fn) {
    Array.prototype.forEach.call(document.querySelectorAll('[data-pwa-install]'), fn);
  }
  function setControlHidden(el, hide) {
    if (hide) { el.setAttribute('hidden', ''); } else { el.removeAttribute('hidden'); }
  }

  function updatePwaInstallButtons() {
    var show;
    if (isStandalone()) { show = false; }        // already installed / running as an app
    else if (deferredPrompt) { show = true; }    // Chrome/Edge/Android: native prompt is ready
    else if (isIOS()) { show = true; }           // iOS Safari: manual instructions
    else { show = false; }                       // no reliable path -> hide (never a dead button)
    forEachInstallControl(function (el) { setControlHidden(el, !show); });
  }

  function doInstall(trigger) {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then(function (choice) {
        if (choice && choice.outcome === 'accepted') { deferredPrompt = null; }  // appinstalled will hide
        updatePwaInstallButtons();               // dismissed -> keep usable while still promptable
      }).catch(function () {});
    } else if (isIOS()) {
      showIosInstructions(trigger);
    }
  }

  // Accessible iOS "Add to Home Screen" dialog (Escape/close, focus trapped/restored).
  function showIosInstructions(trigger) {
    if (document.getElementById('pwa-ios-help')) { return; }
    var overlay = document.createElement('div');
    overlay.className = 'pwa-ios-overlay'; overlay.id = 'pwa-ios-help';
    var dialog = document.createElement('div');
    dialog.className = 'pwa-ios-dialog';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'pwa-ios-title');
    dialog.tabIndex = -1;
    dialog.innerHTML =
      '<h2 id="pwa-ios-title">Instalace na iPhone nebo iPad</h2>' +
      '<ol><li>Klepněte v Safari na tlačítko Sdílet.</li>' +
      '<li>Vyberte „Přidat na plochu“.</li>' +
      '<li>Potvrďte tlačítkem „Přidat“.</li></ol>';
    var close = document.createElement('button');
    close.type = 'button'; close.className = 'btn btn-secondary pwa-ios-close'; close.textContent = 'Zavřít';
    dialog.appendChild(close);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    function dismiss() {
      if (overlay.parentNode) { overlay.parentNode.removeChild(overlay); }
      document.removeEventListener('keydown', onKey, true);
      if (trigger && typeof trigger.focus === 'function') { trigger.focus(); }
    }
    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); dismiss(); }
      else if (e.key === 'Tab') { e.preventDefault(); close.focus(); }   // only the close button is focusable
    }
    close.addEventListener('click', dismiss);
    overlay.addEventListener('click', function (e) { if (e.target === overlay) { dismiss(); } });
    document.addEventListener('keydown', onKey, true);
    close.focus();
  }

  // Delegated click for every install button, on any page.
  document.addEventListener('click', function (e) {
    var btn = e.target && e.target.closest ? e.target.closest('.js-pwa-install') : null;
    if (btn) { e.preventDefault(); doInstall(btn); }
  });

  // Initial state as soon as the DOM is ready (covers pages loaded after the
  // beforeinstallprompt event, and iOS where the event never fires).
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', updatePwaInstallButtons);
  } else { updatePwaInstallButtons(); }
})();
