/* Formace 2.0 companion: mode toggle, validation panel, pool search/filter,
   fill-substitutes, print. Runs after lines.js; reuses the same slot DOM. */
(function () {
  'use strict';
  function ready(fn) { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn); else fn(); }
  ready(function () {
    var form = document.getElementById('linesForm');
    if (!form) return;
    var $ = function (s, r) { return (r || document).querySelector(s); };
    var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

    // ---------- mode toggle (5v5 / special teams) ----------
    var modeBtns = $$('[data-mode-btn]');
    var modes = $$('.lines-mode');
    function setMode(m) {
      modes.forEach(function (sec) { sec.hidden = (sec.getAttribute('data-mode') !== m); });
      modeBtns.forEach(function (b) {
        var on = b.getAttribute('data-mode-btn') === m;
        b.classList.toggle('is-active', on); b.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      try { localStorage.setItem('lines_mode', m); } catch (e) {}
    }
    modeBtns.forEach(function (b) { b.addEventListener('click', function () { setMode(b.getAttribute('data-mode-btn')); }); });
    try { var saved = localStorage.getItem('lines_mode'); if (saved === 'st') setMode('st'); } catch (e) {}

    // ---------- pool search + position filters ----------
    var search = $('#poolSearch');
    var curFilter = 'all';
    function applyPool() {
      var q = (search && search.value ? search.value.trim().toLowerCase() : '');
      $$('.pool-wrap').forEach(function (w) {
        w.style.display = (curFilter === 'all' || w.getAttribute('data-pos') === curFilter) ? '' : 'none';
      });
      $$('.pl-item').forEach(function (it) {
        var name = it.getAttribute('data-name') || '';
        it.style.display = (!q || name.indexOf(q) >= 0) ? '' : 'none';
      });
    }
    if (search) search.addEventListener('input', applyPool);
    $$('.pool-chip').forEach(function (ch) {
      ch.addEventListener('click', function () {
        $$('.pool-chip').forEach(function (x) { x.classList.remove('is-active'); });
        ch.classList.add('is-active'); curFilter = ch.getAttribute('data-filter'); applyPool();
      });
    });

    // ---------- validation ----------
    var panel = $('#lineup-validation');
    function grp(slot) { return slot.getAttribute('data-group') || '5v5'; }
    function fillOf(slot) { return slot.querySelector('.fill'); }
    function validate() {
      if (!panel) return;
      var issues = [];
      // duplicate same player within the same group (line+PP overlap is allowed)
      var byGroup = {};
      $$('.slot').forEach(function (s) {
        var f = fillOf(s); if (!f) return;
        var g = grp(s), id = f.getAttribute('data-id');
        (byGroup[g] = byGroup[g] || {});
        (byGroup[g][id] = byGroup[g][id] || []).push(f.querySelector('span') ? f.querySelector('span').textContent : '?');
      });
      Object.keys(byGroup).forEach(function (g) {
        Object.keys(byGroup[g]).forEach(function (id) {
          if (byGroup[g][id].length > 1) issues.push('Duplicitní hráč: ' + byGroup[g][id][0] + ' je ve více slotech');
        });
      });
      // incomplete 5v5 lines
      for (var ln = 1; ln <= 4; ln++) {
        var names = ['L' + ln + 'LW', 'L' + ln + 'C', 'L' + ln + 'RW', 'D' + ln + 'LD', 'D' + ln + 'RD'];
        var filled = names.filter(function (n) { var s = $('.slot[data-slot="' + n + '"]'); return s && fillOf(s); }).length;
        if (filled > 0 && filled < 5) issues.push(ln + '. lajna je neúplná (' + filled + '/5)');
      }
      // goalie
      var g1 = $('.slot[data-slot="G1"]'); if (g1 && !fillOf(g1)) issues.push('Chybí první brankář (G1)');
      // incomplete special-teams units
      $$('.st-unit').forEach(function (u) {
        var slots = $$('.slot', u), filled = slots.filter(fillOf).length;
        if (filled > 0 && filled < slots.length) {
          var h = u.querySelector('h4'); issues.push('Neúplná jednotka: ' + (h ? h.textContent : '') + ' (' + filled + '/' + slots.length + ')');
        }
      });
      // full-name tooltip fallback for 2-line-clamped chips (Option B)
      $$('.slot .fill > span').forEach(function (s) { var t = (s.textContent || '').trim(); if (t && s.title !== t) s.title = t; });
      if (!issues.length) {
        panel.className = 'lineup-valid is-ok';
        panel.innerHTML = '<strong>✓ Sestava je v pořádku</strong>';
      } else {
        panel.className = 'lineup-valid is-warn';
        panel.innerHTML = '<strong>⚠ ' + issues.length + ' upozornění</strong><ul>' +
          issues.map(function (i) { return '<li>' + i.replace(/[<>&]/g, '') + '</li>'; }).join('') + '</ul>';
      }
    }
    // recompute on any DOM change in the form (lines.js mutates fills directly)
    var deb = null;
    var mo = new MutationObserver(function () { clearTimeout(deb); deb = setTimeout(validate, 120); });
    mo.observe(form, { childList: true, subtree: true });
    form.addEventListener('click', function () { clearTimeout(deb); deb = setTimeout(validate, 120); });
    setTimeout(validate, 300);

    // ---------- fill substitutes from remaining players ----------
    var btnFill = $('#btnFillSubs');
    if (btnFill) btnFill.addEventListener('click', function () {
      var used = {};
      $$('.slot').forEach(function (s) { if ((s.getAttribute('data-group') || '5v5') === '5v5') { var f = fillOf(s); if (f) used[f.getAttribute('data-id')] = true; } });
      var remaining = {};
      $$('.pl-item').forEach(function (it) { var id = it.getAttribute('data-id'); if (!used[id]) { var p = it.getAttribute('data-pos'); (remaining[p] = remaining[p] || []).push(it); } });
      ['SUBF1', 'SUBF2', 'SUBF3', 'SUBD1', 'SUBD2', 'SUBG1'].forEach(function (sn) {
        var slot = $('.slot[data-slot="' + sn + '"]'); if (!slot || fillOf(slot)) return;
        var pos = slot.getAttribute('data-accept'); var list = remaining[pos] || [];
        var it = list.shift(); if (!it) return;
        var id = it.getAttribute('data-id'); var name = (it.textContent || '').replace(/^\s*\S+\s+/, '');
        var hid = slot.querySelector('input[type=hidden]'); if (hid) hid.value = id;
        var ph = slot.querySelector('.ph'); if (ph) ph.remove();
        var fill = document.createElement('div'); fill.className = 'fill'; fill.setAttribute('data-id', id);
        var sp = document.createElement('span'); sp.textContent = name;
        var bx = document.createElement('button'); bx.type = 'button'; bx.className = 'btn-x'; bx.textContent = '×';
        bx.addEventListener('click', function () { hid.value = ''; fill.remove(); var p2 = document.createElement('span'); p2.className = 'ph'; p2.textContent = 'Přetáhni…'; slot.appendChild(p2); validate(); });
        fill.appendChild(sp); fill.appendChild(bx); slot.appendChild(fill);
        used[id] = true;
      });
      validate();
    });

    // ---------- print ----------
    var btnPrint = $('#btnPrint');
    if (btnPrint) btnPrint.addEventListener('click', function () { window.print(); });

    applyPool();
  });
})();
