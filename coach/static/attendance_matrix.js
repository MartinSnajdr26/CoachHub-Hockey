/* CoachHub attendance matrix — cell editing (AJAX, no reload), detail panels,
   filters. Reads server data from #am-data; recomputes summaries client-side. */
(function () {
  'use strict';
  // Range persistence shared with the player page (localStorage 'att_range').
  // If the URL has no range, restore the remembered one; else remember it.
  try {
    var _p = new URLSearchParams(window.location.search);
    if (!_p.get('range')) {
      var _lr = localStorage.getItem('att_range');
      if (_lr) { var _u = new URL(window.location.href); _u.searchParams.set('range', _lr); window.location.replace(_u.toString()); return; }
    } else { localStorage.setItem('att_range', _p.get('range')); }
  } catch (e) {}

  var dataEl = document.getElementById('am-data');
  if (!dataEl) return;
  var DATA;
  try { DATA = JSON.parse(dataEl.textContent || '{}'); } catch (e) { return; }
  var CFG = window.AM_CFG || {};
  var MARKS = { going: '✓', not_going: '✕', maybe: '?', unknown: '·' };
  var CYCLE = { unknown: 'going', going: 'not_going', not_going: 'maybe', maybe: 'unknown' };
  var STATUSES = ['going', 'not_going', 'maybe', 'unknown'];

  // in-memory model: status[pid][key] = status
  var status = {};
  (DATA.players || []).forEach(function (p) { status[p.id] = {}; });
  var smap = DATA.status_map || {};
  Object.keys(smap).forEach(function (pid) {
    Object.keys(smap[pid]).forEach(function (k) { (status[pid] = status[pid] || {})[k] = smap[pid][k]; });
  });
  var events = DATA.events || [];
  var players = DATA.players || [];
  var todayISO = new Date().toISOString().slice(0, 10);

  function statusOf(pid, key) { return (status[pid] && status[pid][key]) || 'unknown'; }
  function colorOf(pct, total) { if (!total) return 'none'; if (pct >= 80) return 'green'; if (pct >= 60) return 'yellow'; return 'red'; }
  function pctOf(go, total) { return total ? Math.round(go * 100 / total) : 0; }

  // ---- recompute + repaint ----
  function recomputeEvent(key) {
    var c = { going: 0, not_going: 0, maybe: 0, unknown: 0 };
    players.forEach(function (p) { c[statusOf(p.id, key)]++; });
    var total = players.length, pct = pctOf(c.going, total), color = colorOf(pct, total);
    var sum = document.querySelector('[data-ev-sum="' + cssEsc(key) + '"]');
    if (sum) sum.textContent = c.going + ' / ' + total;
    var bar = document.querySelector('[data-ev-bar="' + cssEsc(key) + '"]');
    if (bar) bar.style.width = pct + '%';
    var th = document.querySelector('.am-hcell[data-event-key="' + cssEsc(key) + '"]');
    if (th) { ['green', 'yellow', 'red', 'none'].forEach(function (x) { th.classList.remove('am-col--' + x); }); th.classList.add('am-col--' + color); }
    var ev = events.find(function (e) { return e.key === key; });
    if (ev) ev.summary = { going: c.going, not_going: c.not_going, maybe: c.maybe, unknown: c.unknown, total: total, pct: pct, color: color };
  }
  function recomputePlayer(pid) {
    var c = { going: 0, not_going: 0, maybe: 0, unknown: 0 };
    events.forEach(function (e) { c[statusOf(pid, e.key)]++; });
    var total = events.length, pct = pctOf(c.going, total);
    var pe = document.querySelector('[data-p-pct="' + pid + '"]');
    if (pe) { pe.textContent = pct + '%'; pe.className = 'am-pct--' + colorOf(pct, total); }
    // streak from most recent past events
    var past = events.filter(function (e) { return e.day <= todayISO; })
                     .sort(function (a, b) { return a.day < b.day ? -1 : 1; });
    var streak = 0;
    for (var i = past.length - 1; i >= 0; i--) { if (statusOf(pid, past[i].key) === 'going') streak++; else break; }
    var se = document.querySelector('[data-p-streak="' + pid + '"]');
    if (se) se.textContent = streak;
    var pv = players.find(function (p) { return p.id === pid; });
    if (pv) { pv.summary.going = c.going; pv.summary.pct = pct; pv.streak = streak; }
  }
  function recomputeKPIs() {
    var rated = players.filter(function (p) { return p.summary.total > 0; });
    var avg = rated.length ? Math.round(rated.reduce(function (s, p) { return s + p.summary.pct; }, 0) / rated.length) : 0;
    var up = events.filter(function (e) { return e.is_upcoming; });
    var ut = 0, ug = 0, nr = 0;
    up.forEach(function (e) { ut += e.summary.total; ug += e.summary.going; nr += e.summary.unknown; });
    setKpi(0, avg + '%'); setKpi(1, pctOf(ug, ut) + '%'); setKpi(2, nr);
  }
  function setKpi(i, val) { var el = document.querySelectorAll('.am-kpi .am-kpi-v')[i]; if (el) el.textContent = val; }
  function cssEsc(s) { return (s || '').replace(/"/g, '\\"'); }

  // ---- cell editing ----
  function setCell(btn, next) {
    var pid = parseInt(btn.getAttribute('data-pid'), 10), key = btn.getAttribute('data-key');
    var prev = statusOf(pid, key);
    status[pid] = status[pid] || {}; status[pid][key] = next;
    paintCell(btn, next);
    recomputeEvent(key); recomputePlayer(pid); recomputeKPIs();
    fetch(CFG.cellUrl, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CFG.csrf },
      body: JSON.stringify({ player_id: pid, event_key: key, status: next })
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
      .then(function (j) { if (j && j.event_summary) { /* server authoritative; UI already matches */ } })
      .catch(function () {
        status[pid][key] = prev; paintCell(btn, prev);
        recomputeEvent(key); recomputePlayer(pid); recomputeKPIs();
        announce('Uložení se nezdařilo, zkus to znovu.');
      });
  }
  function paintCell(btn, st) {
    STATUSES.forEach(function (s) { btn.classList.remove('am-' + s); });
    btn.classList.add('am-' + st);
    btn.setAttribute('data-status', st);
    var m = btn.querySelector('.am-mark'); if (m) m.textContent = MARKS[st];
  }
  function announce(msg) { var p = document.getElementById('am-panel-body'); /* lightweight */ try { console.warn(msg); } catch (e) {} alert(msg); }

  // ---- panels ----
  var overlay = document.getElementById('am-overlay');
  var panel = document.getElementById('am-panel');
  var panelBody = document.getElementById('am-panel-body');
  function openPanel(html) { panelBody.innerHTML = html; panel.hidden = false; overlay.hidden = false; document.body.classList.add('am-panel-open'); }
  function closePanel() { panel.hidden = true; overlay.hidden = true; document.body.classList.remove('am-panel-open'); }
  function esc(s) { return (s == null ? '' : String(s)).replace(/[&<>"]/g, function (m) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[m]; }); }
  function bar(pct, color) { return '<span class="am-pbar am-pbar--' + color + '"><i style="width:' + pct + '%"></i></span>'; }

  function eventPanel(key) {
    var e = events.find(function (x) { return x.key === key; }); if (!e) return;
    var s = e.summary, names = e.names || {};
    function group(label, arr, cls) { return '<div class="am-grp"><h4 class="' + cls + '">' + label + ' (' + arr.length + ')</h4><div>' + (arr.length ? arr.map(esc).join(', ') : '—') + '</div></div>'; }
    function posRow(pos, lbl) { var b = e.by_position[pos] || {}; return '<tr><td>' + lbl + '</td><td>' + (b.going || 0) + '</td><td>' + (b.not_going || 0) + '</td><td>' + (b.maybe || 0) + '</td><td>' + (b.unknown || 0) + '</td></tr>'; }
    openPanel(
      '<h3>' + (e.kind === 'match' ? '🏒 ' : '🧊 ') + esc(e.title) + '</h3>' +
      '<p class="am-muted">' + esc(e.day_full) + (e.time ? ' · ' + esc(e.time) : '') + ' · ' + (e.kind === 'match' ? 'Zápas' : 'Trénink') + (e.source === 'tymuj' ? ' · tymuj.cz' : '') + '</p>' +
      '<div class="am-bigpct am-pct--' + s.color + '">' + s.pct + '%</div>' + bar(s.pct, s.color) +
      '<div class="am-statgrid">' +
        '<div><b>' + s.going + '</b><span>Jde</span></div><div><b>' + s.not_going + '</b><span>Nejde</span></div>' +
        '<div><b>' + s.maybe + '</b><span>Možná</span></div><div><b>' + s.unknown + '</b><span>Bez odp.</span></div></div>' +
      '<h4>Podle pozice</h4><table class="am-postable"><thead><tr><th></th><th>✓</th><th>✕</th><th>?</th><th>•</th></tr></thead><tbody>' +
        posRow('G', 'Brankáři') + posRow('D', 'Obránci') + posRow('F', 'Útočníci') + '</tbody></table>' +
      group('✓ Jde', names.going || [], 'am-c-go') + group('✕ Nejde', names.not_going || [], 'am-c-no') +
      group('? Možná', names.maybe || [], 'am-c-mb') + group('• Bez odpovědi', names.unknown || [], 'am-c-un')
    );
  }
  function playerPanel(pid) {
    var p = players.find(function (x) { return x.id === pid; }); if (!p) return;
    var s = p.summary;
    var spark = (p.recent || []).map(function (r) { return '<i class="am-sp am-sp-' + r.status + '" title="' + esc(r.day) + '">' + MARKS[r.status] + '</i>'; }).join('');
    openPanel(
      '<h3><span class="am-avatar am-pos-' + esc(p.position) + '">' + esc(p.initials) + '</span> ' + esc(p.name) + '</h3>' +
      '<p class="am-muted">Pozice: ' + esc(p.position) + '</p>' +
      '<div class="am-bigpct am-pct--' + s.color + '">' + s.pct + '%</div>' + bar(s.pct, s.color) +
      '<div class="am-statgrid">' +
        '<div><b>' + s.going + '</b><span>Jde</span></div><div><b>' + s.not_going + '</b><span>Nejde</span></div>' +
        '<div><b>' + s.maybe + '</b><span>Možná</span></div><div><b>' + s.unknown + '</b><span>Bez odp.</span></div></div>' +
      '<div class="am-statgrid am-statgrid--2">' +
        '<div><b>' + p.trainings.pct + '%</b><span>Tréninky (' + p.trainings.going + '/' + p.trainings.total + ')</span></div>' +
        '<div><b>' + p.games.pct + '%</b><span>Zápasy (' + p.games.going + '/' + p.games.total + ')</span></div>' +
        '<div><b>🔥 ' + p.streak + '</b><span>Aktuální série</span></div>' +
        '<div><b>' + p.longest_streak + '</b><span>Nejdelší série</span></div></div>' +
      '<h4>Poslední docházka</h4><div class="am-spark">' + (spark || '—') + '</div>'
    );
  }

  // ---- wiring ----
  var mainPane = document.getElementById('am-main');
  var headerPane = document.getElementById('am-header');
  var leftPane = document.getElementById('am-left');

  // FREEZE PANES: main pane owns scrolling; sync the header (X) and left (Y).
  if (mainPane) {
    mainPane.addEventListener('scroll', function () {
      if (headerPane) headerPane.scrollLeft = mainPane.scrollLeft;
      if (leftPane) leftPane.scrollTop = mainPane.scrollTop;
    }, { passive: true });
  }

  // cell editing (main pane)
  if (mainPane) {
    mainPane.addEventListener('click', function (ev) {
      var cell = ev.target.closest('.am-cell');
      if (cell && CFG.isCoach && !cell.disabled) { setCell(cell, CYCLE[cell.getAttribute('data-status')] || 'going'); }
    });
  }
  // event header click -> event panel
  if (headerPane) {
    var headOpen = function (ev) {
      var h = ev.target.closest('.am-hcell'); if (h) { ev.preventDefault(); eventPanel(h.getAttribute('data-event-key')); }
    };
    headerPane.addEventListener('click', headOpen);
    headerPane.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') headOpen(ev); });
  }
  // player name click -> player panel
  if (leftPane) {
    var nameOpen = function (ev) {
      var n = ev.target.closest('.am-lcell'); if (n) { ev.preventDefault(); playerPanel(parseInt(n.getAttribute('data-player-id'), 10)); }
    };
    leftPane.addEventListener('click', nameOpen);
    leftPane.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' || ev.key === ' ') nameOpen(ev); });
  }
  document.getElementById('am-panel-close').addEventListener('click', closePanel);
  overlay.addEventListener('click', closePanel);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closePanel(); });

  // quick range chips
  Array.prototype.forEach.call(document.querySelectorAll('.am-chip'), function (ch) {
    ch.addEventListener('click', function () {
      var v = ch.getAttribute('data-range');
      try { localStorage.setItem('att_range', v); } catch (e) {}
      document.getElementById('am-range').value = v;
      document.getElementById('am-filters').submit();
    });
  });
  // client-side player search — hide the player's row in BOTH panes to keep
  // the left column and main grid vertically aligned.
  var search = document.getElementById('am-player-search');
  if (search) search.addEventListener('input', function () {
    var q = search.value.trim().toLowerCase();
    function apply(el) { el.style.display = (!q || (el.getAttribute('data-name') || '').indexOf(q) >= 0) ? '' : 'none'; }
    Array.prototype.forEach.call(document.querySelectorAll('.am-lcell'), apply);
    Array.prototype.forEach.call(document.querySelectorAll('.am-mrow'), apply);
  });
})();
