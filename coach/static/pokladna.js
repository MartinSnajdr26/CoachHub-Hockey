/* Pokladna — one-click payment status (AJAX, no reload). */
(function () {
  'use strict';
  var cfg = window.PK_CFG || {};
  var list = document.getElementById('pk-list');
  if (!list || !cfg.url) return;
  var LABEL = { paid: 'Zaplaceno', partial: 'Částečně', unpaid: 'Nezaplaceno' };

  function setSummary(s) {
    if (!s) return;
    ['paid', 'partial', 'unpaid'].forEach(function (k) {
      var el = document.querySelector('[data-sum="' + k + '"]'); if (el) el.textContent = s[k];
    });
    var p2 = document.querySelector('[data-sum="paid2"]'); if (p2) p2.textContent = s.paid;
  }

  list.addEventListener('click', function (e) {
    var btn = e.target.closest('.pk-btn'); if (!btn) return;
    var row = btn.closest('.pk-row'); if (!row) return;
    var status = btn.getAttribute('data-status');
    var pid = row.getAttribute('data-player-id');
    var prev = row.getAttribute('data-status');
    if (status === prev) return;
    paint(row, status);                 // optimistic
    fetch(cfg.url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cfg.csrf },
      body: JSON.stringify({ period_id: cfg.period, player_id: parseInt(pid, 10), status: status })
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
      .then(function (j) { if (j && j.summary) setSummary(j.summary); })
      .catch(function () { paint(row, prev); alert('Uložení se nezdařilo.'); });
  });

  function paint(row, status) {
    row.setAttribute('data-status', status);
    row.className = row.className.replace(/pk-row--\w+/, 'pk-row--' + status);
    var badge = row.querySelector('.pk-badge');
    if (badge) { badge.className = 'pk-badge pk-badge--' + status; badge.textContent = LABEL[status]; }
    row.querySelectorAll('.pk-btn').forEach(function (b) {
      var on = b.getAttribute('data-status') === status;
      b.classList.toggle('is-active', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }
})();
