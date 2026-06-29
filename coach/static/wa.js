/* ============================================================
 * CoachHub WhatsApp integration
 * ------------------------------------------------------------
 * Three cleanly separated layers so a future WhatsApp Business
 * API can replace ONLY the delivery layer without touching
 * templates or the preview UI:
 *
 *   1) CoachHubWA.tpl       — pure message-template generators
 *   2) CoachHubWA.openPreview — preview modal UI (see exact text)
 *   3) CoachHubWA.delivery  — delivery mechanism (deep link / share / copy)
 *
 * No phone numbers, no group IDs, no automatic sending, no paid API.
 * Players are reminded to confirm attendance in Týmuj (not CoachHub).
 * ============================================================ */
(function () {
  'use strict';

  function teamName() {
    return (document.body && document.body.getAttribute('data-team-name')) || 'CoachHub';
  }
  var TYMUJ_LINE = 'Prosím potvrďte svou účast v Týmuj.';

  /* ---------- 1) TEMPLATE GENERATION (pure functions) ---------- */
  var tpl = {
    teamMessage: function (text) {
      return '🏒 ' + teamName() + '\n\n📢 Zpráva pro tým\n\n' + (text || '').trim();
    },
    practice: function (o) {
      o = o || {};
      var L = ['🏒 ' + teamName(), '', '🏋️ Trénink', ''];
      if (o.when) L.push('📅 ' + o.when);
      if (o.location) L.push('📍 ' + o.location);
      if (o.title && o.title !== 'Trénink') L.push('', o.title);
      if (o.notes) L.push('', o.notes);
      L.push('', TYMUJ_LINE);
      return L.join('\n');
    },
    game: function (o) {
      o = o || {};
      var L = ['🏒 ' + teamName(), '', '🥅 Zápas', ''];
      if (o.title) L.push('🆚 ' + o.title);
      if (o.when) L.push('📅 ' + o.when);
      if (o.location) L.push('📍 ' + o.location);
      if (o.meeting) L.push('🚌 Sraz: ' + o.meeting);
      if (o.roster && o.roster.length) { L.push('', '📋 Nominace:'); o.roster.forEach(function (n) { L.push('• ' + n); }); }
      if (o.notes) L.push('', o.notes);
      L.push('', TYMUJ_LINE);
      return L.join('\n');
    },
    attendance: function (o) {
      o = o || {};
      var kindLabel = (o.kind === 'match') ? 'Zápas' : 'Trénink';
      var L = ['🏒 ' + teamName(), '', '⏰ Připomínka účasti', ''];
      L.push('📅 ' + kindLabel + ': ' + (o.title || ''));
      if (o.when) L.push('🕒 ' + o.when);
      L.push('', TYMUJ_LINE);
      if (o.audienceLabel && o.names && o.names.length) {
        L.push('', o.audienceLabel + ':');
        o.names.forEach(function (n) { L.push('• ' + n); });
      }
      return L.join('\n');
    },
    payment: function (o) {
      var L = ['💰 ' + teamName(), '', 'Měsíční příspěvek', (o.month || ''), '', 'Částka:', (o.amount || '') + ' Kč', ''];
      L.push((o.audienceLabel || 'Nezaplatili') + ':');
      if (o.names && o.names.length) { o.names.forEach(function (n) { L.push(n); }); }
      else { L.push('—'); }
      L.push('', 'Děkujeme.');
      return L.join('\n');
    },
    lineup: function (o) {
      o = o || {};
      var out = ['🏒 ' + teamName(), '', '📋 Sestava', ''];
      (o.lines || []).forEach(function (ln) {
        out.push(ln.title + ':');
        if (ln.fwd && ln.fwd.length) out.push('   ' + ln.fwd.join(' – '));
        if (ln.def && ln.def.length) out.push('   ' + ln.def.join(' – '));
        out.push('');
      });
      if (o.goalies && o.goalies.length) out.push('Brankáři:', '   ' + o.goalies.join(', '));
      return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
    }
  };

  /* ---------- 3) DELIVERY (the swappable layer) ----------
   * Today: WhatsApp deep link + native share + clipboard.
   * Future: replace open()/share() with a call to a server endpoint
   * that fans out via the WhatsApp Business API / push service.
   * The template + preview layers stay identical. */
  var delivery = {
    waLink: function (text) { return 'https://wa.me/?text=' + encodeURIComponent(text); },
    open: function (text) {
      var url = delivery.waLink(text);
      try { window.open(url, '_blank', 'noopener'); } catch (e) { window.location.href = url; }
    },
    canShare: function () { return !!(navigator && navigator.share); },
    share: function (text) { if (navigator.share) { navigator.share({ text: text }).catch(function () {}); } },
    copy: function (text, cb) {
      function done(ok) { if (cb) cb(ok); }
      function fallback() {
        try {
          var ta = document.createElement('textarea');
          ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
          document.body.appendChild(ta); ta.focus(); ta.select();
          document.execCommand('copy'); document.body.removeChild(ta); done(true);
        } catch (e) { done(false); }
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, fallback);
      } else { fallback(); }
    }
  };

  /* ---------- 2) PREVIEW UI (modal) ---------- */
  var modal, taEl, titleEl, audWrap, copyBtn, openBtn, shareBtn;
  function buildModal() {
    if (modal) return;
    modal = document.createElement('div');
    modal.className = 'modal wa-modal';
    modal.innerHTML =
      '<div class="modal-backdrop" data-wa-close></div>' +
      '<div class="modal-dialog modal-dialog--wide" role="dialog" aria-modal="true">' +
        '<div class="modal-header"><h3 class="wa-title">Náhled zprávy</h3>' +
        '<button type="button" class="modal-close" data-wa-close aria-label="Zavřít">✕</button></div>' +
        '<div class="wa-audiences" data-wa-aud></div>' +
        '<textarea class="wa-text" data-wa-ta rows="11" aria-label="Text zprávy"></textarea>' +
        '<p class="wa-hint muted">Zkontroluj text. Otevře se WhatsApp s předvyplněnou zprávou — odeslání potvrdíš ručně.</p>' +
        '<div class="modal-footer">' +
          '<button type="button" class="btn-secondary btn-sm" data-wa-copy>Kopírovat text</button>' +
          '<button type="button" class="btn-ghost btn-sm" data-wa-share style="display:none;">Sdílet…</button>' +
          '<button type="button" class="btn" data-wa-open>Otevřít WhatsApp</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(modal);
    taEl = modal.querySelector('[data-wa-ta]');
    titleEl = modal.querySelector('.wa-title');
    audWrap = modal.querySelector('[data-wa-aud]');
    copyBtn = modal.querySelector('[data-wa-copy]');
    openBtn = modal.querySelector('[data-wa-open]');
    shareBtn = modal.querySelector('[data-wa-share]');
    modal.addEventListener('click', function (e) { if (e.target.closest('[data-wa-close]')) close(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && modal.classList.contains('open')) close(); });
    copyBtn.addEventListener('click', function () {
      delivery.copy(taEl.value, function (ok) {
        copyBtn.textContent = ok ? '✓ Zkopírováno' : 'Označ a zkopíruj';
        setTimeout(function () { copyBtn.textContent = 'Kopírovat text'; }, 1800);
      });
    });
    openBtn.addEventListener('click', function () { delivery.open(taEl.value); });
    shareBtn.addEventListener('click', function () { delivery.share(taEl.value); });
  }
  function close() { if (modal) modal.classList.remove('open'); }

  function openPreview(opts) {
    opts = opts || {};
    buildModal();
    titleEl.textContent = opts.title || 'Náhled zprávy';
    audWrap.innerHTML = '';
    if (opts.audiences && opts.audiences.length) {
      audWrap.style.display = '';
      opts.audiences.forEach(function (a, i) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'wa-chip' + (i === 0 ? ' is-active' : '');
        b.textContent = a.label;
        b.addEventListener('click', function () {
          audWrap.querySelectorAll('.wa-chip').forEach(function (x) { x.classList.remove('is-active'); });
          b.classList.add('is-active');
          taEl.value = a.text();
        });
        audWrap.appendChild(b);
      });
      taEl.value = opts.audiences[0].text();
    } else {
      audWrap.style.display = 'none';
      taEl.value = opts.text || '';
    }
    shareBtn.style.display = delivery.canShare() ? '' : 'none';
    modal.classList.add('open');
    setTimeout(function () { try { taEl.focus(); taEl.setSelectionRange(0, 0); taEl.scrollTop = 0; } catch (e) {} }, 30);
  }

  /* ---------- Context gathering (reads existing DOM only) ---------- */
  function gatherAttendance(col) {
    var res = { going: [], not_going: [], unknown: [] };
    document.querySelectorAll('.attn-select[data-col="' + col + '"]').forEach(function (s) {
      var tr = s.closest('tr'); if (!tr) return;
      var cell = tr.querySelector('td'); var name = cell ? cell.textContent.trim() : '';
      if (name && res[s.value]) res[s.value].push(name);
    });
    return res;
  }
  function parseLineup() {
    var lines = [];
    document.querySelectorAll('#formations .formation[data-line]').forEach(function (f) {
      var title = ((f.querySelector('h3') || {}).textContent || '').replace(/\s+/g, ' ').trim();
      function names(sel) {
        return Array.prototype.map.call(f.querySelectorAll(sel + ' .slot'), function (slot) {
          var fill = slot.querySelector('.fill span'); return fill ? fill.textContent.trim() : null;
        }).filter(Boolean);
      }
      var fwd = names('.slots:not(.slots--def)');
      var def = names('.slots--def');
      if (fwd.length || def.length) lines.push({ title: title, fwd: fwd, def: def });
    });
    var goalies = Array.prototype.map.call(
      document.querySelectorAll('.slots--g .slot .fill span'),
      function (s) { return s.textContent.trim(); }
    ).filter(Boolean);
    return { lines: lines, goalies: goalies };
  }

  /* ---------- Wiring (event delegation; pages only declare buttons) ---------- */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-wa]');
    if (!btn) return;
    e.preventDefault();
    var type = btn.getAttribute('data-wa');

    if (type === 'message') {
      var src = btn.getAttribute('data-wa-source');
      var text = src ? ((document.querySelector(src) || {}).value || '') : (btn.getAttribute('data-wa-text') || '');
      text = (text || '').trim();
      if (!text) { if (src) { var box = document.querySelector(src); if (box) box.focus(); } return; }
      openPreview({ title: 'Sdílet zprávu na WhatsApp', text: tpl.teamMessage(text) });

    } else if (type === 'event') {
      var kind = btn.getAttribute('data-wa-kind') || 'training';
      var o = {
        title: btn.getAttribute('data-wa-title') || '',
        when: btn.getAttribute('data-wa-when') || '',
        location: btn.getAttribute('data-wa-location') || '',
        notes: btn.getAttribute('data-wa-notes') || ''
      };
      openPreview({
        title: (kind === 'match' ? 'Sdílet zápas' : 'Sdílet trénink'),
        text: (kind === 'match') ? tpl.game(o) : tpl.practice(o)
      });

    } else if (type === 'attendance') {
      var col = btn.getAttribute('data-wa-col');
      var meta = {
        kind: btn.getAttribute('data-wa-kind') || 'training',
        title: btn.getAttribute('data-wa-title') || '',
        when: btn.getAttribute('data-wa-when') || ''
      };
      var g = gatherAttendance(col);
      function mk(label, names) { var m = {}; for (var k in meta) m[k] = meta[k]; m.audienceLabel = label; m.names = names; return tpl.attendance(m); }
      openPreview({
        title: 'Připomínka účasti',
        audiences: [
          { label: 'Nepotvrdili (' + g.unknown.length + ')', text: function () { return mk('Nepotvrdili účast', g.unknown); } },
          { label: 'Nepojede (' + g.not_going.length + ')', text: function () { return mk('Nepojedou', g.not_going); } },
          { label: 'Pojede (' + g.going.length + ')', text: function () { return mk('Pojedou', g.going); } },
          { label: 'Všichni', text: function () { return mk('', []); } }
        ]
      });

    } else if (type === 'payment') {
      var month = btn.getAttribute('data-wa-month') || '';
      var amount = btn.getAttribute('data-wa-amount') || '';
      function namesByStatus(sts) {
        return Array.prototype.map.call(document.querySelectorAll('.pk-row'), function (r) {
          return sts.indexOf(r.getAttribute('data-status')) >= 0 ? (r.getAttribute('data-name') || '') : '';
        }).filter(Boolean);
      }
      var unpaid = namesByStatus(['unpaid']);
      var unpaidPartial = namesByStatus(['unpaid', 'partial']);
      function mk(label, names) { return tpl.payment({ month: month, amount: amount, audienceLabel: label, names: names }); }
      openPreview({
        title: 'Připomenout příspěvek',
        audiences: [
          { label: 'Nezaplatili (' + unpaid.length + ')', text: function () { return mk('Nezaplatili', unpaid); } },
          { label: 'Nezaplatili + částečně (' + unpaidPartial.length + ')', text: function () { return mk('Nezaplatili / částečně', unpaidPartial); } }
        ]
      });

    } else if (type === 'lineup') {
      var data = parseLineup();
      if (!data.lines.length && !data.goalies.length) {
        openPreview({ title: 'Sdílet sestavu', text: '🏒 ' + teamName() + '\n\n📋 Sestava\n\n(Sestava je zatím prázdná — nejdřív rozmísti hráče.)' });
      } else {
        openPreview({ title: 'Sdílet sestavu', text: tpl.lineup(data) });
      }
    }
  });

  /* Expose for programmatic use / future API swap */
  window.CoachHubWA = { tpl: tpl, delivery: delivery, openPreview: openPreview };
})();
