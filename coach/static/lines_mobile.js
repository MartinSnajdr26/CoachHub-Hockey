/* Lines mobile controller (<=768px, /lines only).
   ISOLATED from lines.js / lines2.js. Creates NO slot inputs and NO second
   lineup store.

   Reality (verified): lines.css's mobile block HIDES the .lines-swiper and shows
   the #formations desktop grid stacked. That grid is ALSO the authoritative save
   copy (first in DOM). So this controller drives #formations directly:
     - line tabs set body[data-lnm-tab] (1..4 / g / subs); mobile.css reveals the
       one matching card (or the goalie slots / .subs-card);
     - tapping a visible slot opens a bottom-sheet picker that drives the EXISTING
       lines.js tap-to-assign (synthetic clicks on the real .pl-item + the real
       #formations/goalie/subs .slot), so real placeInto/clearSlot/validation run;
     - because we edit the authoritative copy directly, NO swiper->desktop sync is
       needed. The hidden swiper is left untouched.
   All of this is inert above 768px, so desktop is unchanged. */
(function () {
  'use strict';
  function ready(fn){ if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn); else fn(); }
  var MQ = window.matchMedia ? window.matchMedia('(max-width: 768px)') : { matches: false };
  function isMobile(){ return !!MQ.matches; }

  ready(function () {
    var bar = document.querySelector('.lnm-bar');
    var form = document.getElementById('linesForm');
    if (!bar || !form) return;

    var $ = function (s, r) { return (r || document).querySelector(s); };
    var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
    var body = document.body;

    /* ---------- line tabs -> body[data-lnm-tab] (CSS reveals one card) ---------- */
    var tabs = $$('#lnmTabs .lnm-tab');
    function tabValue(t){
      var target = t.getAttribute('data-lnm-target');
      if (target === 'subs') return 'subs';
      var idx = parseInt(t.getAttribute('data-lnm-index'), 10) || 0;
      return idx === 4 ? 'g' : String(idx + 1);   // 0..3 -> line 1..4 ; 4 -> goalie
    }
    function selectTab(t) {
      tabs.forEach(function (x) { var on = x === t; x.classList.toggle('is-active', on); x.setAttribute('aria-selected', on ? 'true' : 'false'); });
      body.setAttribute('data-lnm-tab', tabValue(t));
    }
    tabs.forEach(function (t) { t.addEventListener('click', function () { selectTab(t); }); });
    if (tabs.length) selectTab(tabs[0]);           // default: 1. lajna

    /* ---------- 5v5 / special-teams mode -> body[data-lnm-mode] ---------- */
    function syncMode() {
      var st = $('.lines-mode[data-mode="st"]');
      body.setAttribute('data-lnm-mode', (st && !st.hasAttribute('hidden')) ? 'st' : '5v5');
    }
    $$('[data-mode-btn]').forEach(function (b) { b.addEventListener('click', function () { setTimeout(syncMode, 0); }); });
    syncMode();

    /* ---------- player-picker bottom sheet ---------- */
    var sheet = document.getElementById('lnmPicker');
    var listEl = document.getElementById('lnmPickList');
    var searchEl = document.getElementById('lnmPickSearch');
    var titleEl = document.getElementById('lnmPickTitle');
    var subEl = document.getElementById('lnmPickSub');
    var clearBtn = document.getElementById('lnmPickClear');
    var activeSlot = null;

    function accept(slot){ return slot.getAttribute('data-accept'); }
    function poolItems(){ return $$('.pl-item'); }
    function nameOf(pi){ return (pi.textContent || '').replace(/^\s*\S+\s+/, '').trim(); }
    function assignedSlotOf(id){
      var f = $$('.slot .fill').find(function (x) { return x.getAttribute('data-id') === String(id); });
      return f ? f.closest('.slot').getAttribute('data-slot') : '';
    }
    function slotHumanLabel(slotName){
      var s = $('.slot[data-slot="' + slotName + '"]');
      var lbl = s ? (s.getAttribute('data-label') || '') : '';
      if (/^[LD]\d/.test(slotName)) return slotName[1] + '. lajna · ' + lbl;
      if (/^G\d/.test(slotName)) return 'Brankář ' + slotName;
      if (/^SUB/.test(slotName)) return 'Náhradník';
      if (s && (s.getAttribute('data-group') === 'st')) return 'Speciální · ' + lbl;
      return lbl || slotName;
    }

    function openPicker(slot) {
      activeSlot = slot;
      titleEl.textContent = 'Vybrat hráče';
      subEl.textContent = slotHumanLabel(slot.getAttribute('data-slot'));
      if (searchEl) searchEl.value = '';
      renderList('');
      sheet.style.display = 'block'; requestAnimationFrame(function () { sheet.classList.add('open'); }); body.style.overflow = 'hidden';
      if (searchEl) setTimeout(function () { try { searchEl.focus(); } catch (e) {} }, 240);
    }
    function closePicker() { sheet.classList.remove('open'); body.style.overflow = ''; setTimeout(function () { sheet.style.display = 'none'; }, 200); activeSlot = null; }

    function renderList(q) {
      if (!activeSlot || !listEl) return;
      var acc = accept(activeSlot);
      var curId = (function () { var f = activeSlot.querySelector('.fill'); return f ? f.getAttribute('data-id') : null; })();
      listEl.innerHTML = '';
      poolItems().forEach(function (pi) {
        var pos = pi.getAttribute('data-pos');
        if (acc !== pos && !(acc === 'S' && (pos === 'F' || pos === 'D'))) return;
        if (q && (pi.getAttribute('data-name') || '').indexOf(q) < 0) return;
        var id = pi.getAttribute('data-id'), name = nameOf(pi);
        var used = assignedSlotOf(id);
        var row = document.createElement('button');
        row.type = 'button'; row.className = 'lnm-pick-item';
        if (String(id) === String(curId)) row.classList.add('is-current');
        row.setAttribute('data-id', id);
        row.innerHTML = '<span class="lnm-pick-name">' + name.replace(/[<>&]/g, '') + '</span>' +
          (used ? '<span class="lnm-pick-used">Použit: ' + slotHumanLabel(used) + '</span>' : '');
        row.addEventListener('click', function () { assign(pi); });
        listEl.appendChild(row);
      });
      if (!listEl.children.length) { var e = document.createElement('div'); e.className = 'lnm-pick-empty'; e.textContent = 'Žádný hráč'; listEl.appendChild(e); }
    }

    // Reuse lines.js tap-to-assign: select pool item, then click the (visible,
    // authoritative) slot. lines.js runs placeInto -> fill/group-dedup/badges/
    // validation. We never write inputs ourselves; no sync needed.
    function assign(poolItem) {
      if (!activeSlot) return;
      if (!poolItem.classList.contains('is-selected')) poolItem.click();
      activeSlot.click();
      closePicker();
    }
    if (clearBtn) clearBtn.addEventListener('click', function () {
      if (!activeSlot) return;
      var bx = activeSlot.querySelector('.btn-x');
      if (bx) bx.click();
      closePicker();
    });
    if (searchEl) searchEl.addEventListener('input', function () { renderList((searchEl.value || '').trim().toLowerCase()); });
    sheet.addEventListener('click', function (e) { if (e.target.closest('[data-lnm-close]')) closePicker(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && sheet.classList.contains('open')) closePicker(); });

    // Open the picker on tap of a VISIBLE authoritative slot. On mobile the visible
    // slots are in #formations / the desktop goalie group / .subs-card / ST units —
    // i.e. everything EXCEPT the hidden .lines-swiper. Capture-phase + stopPropagation
    // so lines.js's own slot tap-to-assign does not also fire on mobile. Inert >768px.
    document.addEventListener('click', function (e) {
      if (!isMobile()) return;
      var slot = e.target.closest && e.target.closest('.slot');
      if (!slot) return;
      if (slot.closest('.lines-swiper')) return;   // hidden copy — ignore
      if (e.target.closest('.btn-x')) return;      // explicit remove -> lines.js
      if (sheet.contains(e.target)) return;
      e.preventDefault(); e.stopPropagation();
      openPicker(slot);
    }, true);

    /* ---------- sticky save (reuses the existing #linesForm submit) ---------- */
    var saveBtn = document.getElementById('lnmSave');
    if (saveBtn) saveBtn.addEventListener('click', function () { if (form.requestSubmit) form.requestSubmit(); else form.submit(); });
  });
})();
