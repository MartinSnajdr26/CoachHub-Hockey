/* Communication 2.0 — nickname (localStorage), reactions (one/browser),
   anonymous ownership for player edit/delete, and client-side filters.
   No accounts, no polling. */
(function () {
  'use strict';
  var cfg = window.CM_CFG || {};
  var root = document.getElementById('cm-root');
  if (!root) return;
  var IS_COACH = root.getAttribute('data-is-coach') === '1';
  var EDIT_WINDOW = 15 * 60;

  /* ---- tiny localStorage helpers ---- */
  function lget(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function lset(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function jget(k) { try { return JSON.parse(localStorage.getItem(k) || '{}'); } catch (e) { return {}; } }
  function jset(k, o) { try { localStorage.setItem(k, JSON.stringify(o)); } catch (e) {} }
  function rid() { return (Date.now().toString(36) + Math.random().toString(36).slice(2, 10)); }

  /* ---- nickname prefill + remember ---- */
  var nick = document.getElementById('cm-nick');
  if (nick) {
    nick.value = lget('cm_nick', '');
    nick.addEventListener('change', function () { lset('cm_nick', nick.value.trim()); });
  }

  /* ---- composer: generate per-post token+pub, remember nickname ---- */
  var composer = document.getElementById('cm-composer');
  if (composer) {
    composer.addEventListener('submit', function () {
      var token = rid() + rid(), pub = rid();
      var t = document.getElementById('cm-token'); if (t) t.value = token;
      var p = document.getElementById('cm-pub'); if (p) p.value = pub;
      if (nick) lset('cm_nick', nick.value.trim());
      var owned = jget('cm_owned'); owned[pub] = token; jset('cm_owned', owned);  // map pub -> secret token
    });
  }

  /* ---- character counter ---- */
  var ta = document.getElementById('cm-text'), cnt = document.getElementById('cm-count');
  if (ta && cnt) { var upd = function () { cnt.textContent = ta.value.length; }; ta.addEventListener('input', upd); upd(); }

  /* ---- reveal own edit/delete (coach: all; player: owned + within window) ---- */
  var owned = jget('cm_owned');
  Array.prototype.forEach.call(document.querySelectorAll('.cm-card'), function (card) {
    var age = parseInt(card.getAttribute('data-age') || '0', 10);
    var pub = card.getAttribute('data-owner') || '';
    var myToken = owned[pub];
    var canOwn = !!myToken && age < EDIT_WINDOW;
    if (IS_COACH || canOwn) {
      var editBtn = card.querySelector('.cm-edit-btn');
      var delForm = card.querySelector('.cm-del-form');
      var editForm = card.querySelector('.cm-edit-form');
      if (editBtn) editBtn.hidden = false;
      if (delForm) delForm.hidden = false;
      // players send their secret token so the server can authorize
      if (!IS_COACH && myToken) {
        if (delForm) { var dt = delForm.querySelector('input[name="token"]'); if (dt) dt.value = myToken; }
        if (editForm) { var et = editForm.querySelector('input[name="token"]'); if (et) et.value = myToken; }
      }
    }
  });

  /* ---- inline edit toggle ---- */
  document.addEventListener('click', function (e) {
    var eb = e.target.closest('.cm-edit-btn');
    if (eb) { var c = eb.closest('.cm-card'); var f = c.querySelector('.cm-edit-form'); if (f) f.hidden = !f.hidden; return; }
    var cancel = e.target.closest('.cm-edit-cancel');
    if (cancel) { var f2 = cancel.closest('.cm-edit-form'); if (f2) f2.hidden = true; return; }
  });

  /* ---- reactions: one per browser, click again to remove ---- */
  var mine = jget('cm_reacts');           // { msgId: 'like' }
  Array.prototype.forEach.call(document.querySelectorAll('.cm-reacts'), function (box) {
    var id = box.getAttribute('data-id');
    var cur = mine[id];
    if (cur) { var b = box.querySelector('.cm-react[data-react="' + cur + '"]'); if (b) b.classList.add('is-on'); }
  });
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.cm-react'); if (!btn) return;
    var box = btn.closest('.cm-reacts'); var id = box.getAttribute('data-id');
    var pick = btn.getAttribute('data-react');
    var prev = mine[id] || '';
    var reaction = (prev === pick) ? '' : pick;   // toggle off if same
    fetch(cfg.reactUrl.replace(/0$/, id), {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cfg.csrf },
      body: JSON.stringify({ reaction: reaction, prev: prev })
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
      .then(function (j) {
        if (!j || !j.ok) return;
        Object.keys(j.reactions).forEach(function (k) {
          var c = box.querySelector('.cm-react-c[data-c="' + k + '"]'); if (c) c.textContent = j.reactions[k];
        });
        box.querySelectorAll('.cm-react').forEach(function (b) { b.classList.remove('is-on'); });
        if (reaction) { btn.classList.add('is-on'); mine[id] = reaction; } else { delete mine[id]; }
        jset('cm_reacts', mine);
      }).catch(function () {});
  });

  /* ---- client-side filters (search / category / pinned / important) ---- */
  var search = document.getElementById('cm-search');
  var catF = document.getElementById('cm-cat-filter');
  var onlyPin = document.getElementById('cm-only-pinned');
  var onlyImp = document.getElementById('cm-only-important');
  var empty = document.getElementById('cm-empty');
  function applyFilters() {
    var q = (search && search.value || '').trim().toLowerCase();
    var cat = (catF && catF.value) || '';
    var pin = onlyPin && onlyPin.checked;
    var imp = onlyImp && onlyImp.checked;
    var shown = 0;
    Array.prototype.forEach.call(document.querySelectorAll('.cm-card'), function (card) {
      var ok = true;
      if (q && card.getAttribute('data-search').indexOf(q) < 0) ok = false;
      if (cat && card.getAttribute('data-cat') !== cat) ok = false;
      if (pin && card.getAttribute('data-pinned') !== '1') ok = false;
      if (imp && card.getAttribute('data-important') !== '1') ok = false;
      card.hidden = !ok;
      if (ok) shown++;
    });
    if (empty) { empty.hidden = shown !== 0; if (shown === 0) empty.textContent = 'Nic neodpovídá filtru.'; }
  }
  [search, catF, onlyPin, onlyImp].forEach(function (el) {
    if (!el) return;
    el.addEventListener('input', applyFilters);
    el.addEventListener('change', applyFilters);
  });
})();
