/* CoachHub Hockey — mobile bottom-nav sheets (Team menu + Attendance chooser).
   No-op on desktop (the nav + sheets are display:none there). */
(function () {
  'use strict';

  function wireSheet(triggerId, sheetId) {
    var btn = document.getElementById(triggerId);
    var sheet = document.getElementById(sheetId);
    if (!btn || !sheet) return;

    function open() {
      sheet.classList.add('open');
      sheet.style.display = 'block';
      btn.setAttribute('aria-expanded', 'true');
      document.body.style.overflow = 'hidden';
    }
    function close() {
      sheet.classList.remove('open');
      sheet.style.display = '';
      btn.setAttribute('aria-expanded', 'false');
      document.body.style.overflow = '';
    }

    btn.addEventListener('click', function () {
      if (sheet.classList.contains('open')) { close(); } else { open(); }
    });
    sheet.addEventListener('click', function (e) {
      if (e.target.closest('[data-msheet-close]')) { close(); }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && sheet.classList.contains('open')) { close(); }
    });
    // tapping a destination closes the sheet (navigation proceeds)
    sheet.querySelectorAll('.msheet-grid a, .att-choices a').forEach(function (a) {
      a.addEventListener('click', function () { close(); });
    });
  }

  wireSheet('mnavMore', 'mSheet');        // Team & settings
  wireSheet('mnavDochazka', 'attSheet');  // Attendance: Player vs Team
})();
