# -*- coding: utf-8 -*-
"""Coach edit lock on the team attendance matrix.

UX risk addressed: on a phone the matrix is swiped in both axes, and a swipe
that lands as a tap on a status cell silently rewrote someone's attendance. The
matrix therefore opens LOCKED for coaches and must be explicitly unlocked.

The lock is a UX guard, NOT authorization — `/attendance/cell` stays coach-gated
and team-scoped on the server, and the last test class here re-asserts exactly
that, so nobody can later mistake the JS flag for a permission check.

Browser-level behaviour (tap-while-locked mutates nothing, pane still scrolls,
reload returns to locked) is verified with Playwright; these tests pin the
server-rendered contract and the JS/CSS invariants that make it work.
"""
import os
import re
import unittest
from datetime import date, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import AttendanceEntry, Player, Team, TeamKey, TrainingEvent
from coach.services.keys import hash_team_key
from coach.tests.session_helpers import login_session, login_shared_key_session

LOCK_CSS = os.path.join(app.static_folder, 'attendance_lock.css')
MATRIX_JS = os.path.join(app.static_folder, 'attendance_matrix.js')
MOBILE_CSS = os.path.join(app.static_folder, 'mobile.css')


def _read(path):
    return open(path, encoding='utf-8').read()


def _css_rules(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.findall(r'([^{}]+)\{([^{}]*)\}', text)


class LockBase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                          ADMIN_SECRET_KEY='owner-secret')
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        team = Team(name='HC Test')
        db.session.add(team)
        db.session.flush()
        self.tid = team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        db.session.add(TeamKey(team_id=self.tid, role='player', key_hash=hash_team_key('pk')))
        self.player = Player(team_id=self.tid, name='Jan Novák', position='F')
        db.session.add(self.player)
        ev = TrainingEvent(team_id=self.tid, day=date.today() + timedelta(days=2),
                           time='18:00', title='Trénink', kind='training')
        db.session.add(ev)
        db.session.commit()
        self.pid = self.player.id
        self.ev_key = 'local:%d' % ev.id
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def page(self):
        resp = self.client.get('/dochazka')
        self.assertEqual(resp.status_code, 200)
        return resp.get_data(as_text=True)


class CoachSeesLockedMatrixTest(LockBase):
    def setUp(self):
        super().setUp()
        login_session(self.client, self.tid, 'coach')

    def test_lock_control_is_rendered(self):
        html = self.page()
        self.assertIn('id="amLockToggle"', html)
        self.assertIn('am-lock', html)

    def test_matrix_renders_locked_by_default(self):
        """The safety default: every page load starts locked."""
        html = self.page()
        self.assertRegex(html, r'id="amLockToggle"[^>]*aria-pressed="false"')
        self.assertIn('Úpravy zamčené', html)
        self.assertIn('Odemknout úpravy', html)

    def test_locked_is_the_default_on_every_reload(self):
        for _ in range(3):
            self.assertRegex(self.page(), r'aria-pressed="false"')

    def test_unlocked_labels_are_not_pre_rendered(self):
        """The unlocked wording appears only after the coach acts (via JS)."""
        html = self.page()
        self.assertNotIn('Úpravy povolené', html)
        self.assertNotIn('Zamknout úpravy', html)

    def test_coach_cells_stay_editable_in_markup(self):
        """The lock is a UI state, not a server-side disable — unlocking must
        restore today's behaviour without a reload."""
        html = self.page()
        cell = re.search(r'<button type="button" class="am-cell[^>]*>', html).group(0)
        self.assertNotIn('disabled', cell)

    def test_lock_sits_beside_the_grid_so_mobile_can_show_it(self):
        """`.am-lock` must be a direct child of .am-wrap: the mobile table-first
        rule hides .am-wrap's other children, and the control has to survive."""
        html = self.page()
        wrap = html[html.find('<div class="am-wrap">'):]
        lock_at = wrap.find('class="am-lock"')
        grid_at = wrap.find('class="am-grid"')
        self.assertGreater(lock_at, 0)
        self.assertGreater(grid_at, lock_at, 'lock must precede the grid')
        between = wrap[lock_at:grid_at]
        self.assertEqual(between.count('<div class="am-grid'), 0)

    def test_page_loads_the_lock_stylesheet(self):
        self.assertIn('attendance_lock.css', self.page())

    def test_table_markup_is_untouched(self):
        """Scrolling/inspection must survive: the panes and cells still render."""
        html = self.page()
        for hook in ('id="am-main"', 'id="am-header"', 'id="am-left"',
                     'class="am-grid"', 'am-cell', 'data-pid=', 'data-key='):
            self.assertIn(hook, html)


class PlayerNeverSeesTheLockTest(LockBase):
    """Read-only stays read-only, with no way to switch editing on."""

    def setUp(self):
        super().setUp()
        login_session(self.client, self.tid, 'player', player_id=self.pid)

    def test_no_unlock_control(self):
        html = self.page()
        self.assertNotIn('amLockToggle', html)
        self.assertNotIn('Odemknout úpravy', html)
        self.assertNotIn('Úpravy zamčené', html)

    def test_cells_are_disabled_server_side(self):
        html = self.page()
        cell = re.search(r'<button type="button" class="am-cell[^>]*>', html).group(0)
        self.assertIn('disabled', cell)

    def test_client_config_marks_the_session_as_not_coach(self):
        self.assertIn('isCoach: false', self.page())

    def test_player_still_sees_the_data(self):
        html = self.page()
        self.assertIn('Jan Novák', html)
        self.assertIn('class="am-grid"', html)


class LockIsClientSideOnlyTest(LockBase):
    """§8 — the lock must never be mistaken for authorization."""

    def test_player_cannot_mutate_regardless_of_any_ui_state(self):
        login_session(self.client, self.tid, 'player', player_id=self.pid)
        resp = self.client.post('/attendance/cell', json={
            'player_id': self.pid, 'event_key': self.ev_key, 'status': 'going'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(AttendanceEntry.query.count(), 0)

    def test_shared_key_session_cannot_mutate(self):
        login_shared_key_session(self.client, self.tid)
        resp = self.client.post('/attendance/cell', json={
            'player_id': self.pid, 'event_key': self.ev_key, 'status': 'going'})
        self.assertNotEqual(resp.status_code, 200)
        self.assertEqual(AttendanceEntry.query.count(), 0)

    def test_coach_endpoint_is_unchanged_by_the_lock(self):
        """The server has no notion of the lock: a coach request still succeeds,
        which is why the guard must live in the UI only."""
        login_session(self.client, self.tid, 'coach')
        resp = self.client.post('/attendance/cell', json={
            'player_id': self.pid, 'event_key': self.ev_key, 'status': 'going'})
        self.assertEqual(resp.status_code, 200)
        entry = AttendanceEntry.query.one()
        self.assertEqual(entry.status, 'going')

    def test_other_teams_player_is_still_refused(self):
        other = Team(name='HC Other')
        db.session.add(other)
        db.session.flush()
        foreign = Player(team_id=other.id, name='Cizí', position='D')
        db.session.add(foreign)
        db.session.commit()
        login_session(self.client, self.tid, 'coach')
        resp = self.client.post('/attendance/cell', json={
            'player_id': foreign.id, 'event_key': self.ev_key, 'status': 'going'})
        self.assertEqual(resp.status_code, 404)


class LockImplementationInvariantsTest(unittest.TestCase):
    """The JS/CSS properties the browser behaviour depends on."""

    def setUp(self):
        self.js = _read(MATRIX_JS)
        self.css = _read(LOCK_CSS)

    # -- one source of truth -----------------------------------------
    def test_state_starts_locked(self):
        self.assertRegex(self.js, r'var\s+editUnlocked\s*=\s*false')

    def test_single_guard_helper_exists(self):
        self.assertRegex(self.js, r'function\s+canEdit\s*\(')

    def test_mutation_function_is_guarded(self):
        """setCell is the only thing that POSTs; it must refuse when locked."""
        body = self.js[self.js.find('function setCell'):]
        body = body[:body.find('function paintCell')]
        self.assertIn('canEdit()', body)
        self.assertRegex(body, r'if\s*\(\s*!canEdit\(\)\s*\)\s*return')
        # the guard precedes the network call
        self.assertLess(body.find('canEdit()'), body.find('fetch('))

    def test_click_handler_also_checks_the_guard(self):
        self.assertRegex(self.js, r"closest\('\.am-cell'\)[\s\S]{0,200}canEdit\(\)")

    def test_state_is_never_persisted(self):
        """§6 — reopening the page must always return to locked."""
        for store in ('localStorage', 'sessionStorage', 'document.cookie'):
            for m in re.finditer(re.escape(store) + r'[^\n]*', self.js):
                self.assertNotIn('lock', m.group(0).lower(),
                                 'lock state must not be persisted: %s' % m.group(0))
        self.assertNotIn('editUnlocked', self.js[self.js.find('localStorage'):
                                                 self.js.find('localStorage') + 200])

    # -- locked CSS must not break scrolling -------------------------
    def test_locked_state_disables_only_the_cells(self):
        """pointer-events:none may target .am-cell and nothing broader, or the
        table would stop scrolling."""
        for sel, decls in _css_rules(self.css):
            if 'pointer-events' not in decls or 'none' not in decls:
                continue
            for part in sel.split(','):
                part = part.strip()
                self.assertTrue(part.endswith('.am-cell'),
                                'pointer-events:none on a non-cell selector: %s' % part)

    def test_no_rule_hides_or_freezes_the_scroll_panes(self):
        """A scroll container may appear as an ANCESTOR scope, but must never be
        the element such a rule targets."""
        banned = ('.am-grid', '.am-main-pane', '.am-wrap', '.am-body', '#am-main',
                  '.am-pane')
        for sel, decls in _css_rules(self.css):
            if not re.search(r'pointer-events\s*:\s*none|overflow\s*:\s*hidden', decls):
                continue
            for part in sel.split(','):
                target = re.split(r'[ >+~]+', part.strip())[-1]
                for b in banned:
                    self.assertNotEqual(target, b,
                                        'would block scrolling: %s' % part.strip())

    def test_locked_state_does_not_dim_the_data(self):
        """The coach must still be able to read every value while locked."""
        for sel, decls in _css_rules(self.css):
            if 'am-edit-locked' in sel:
                m = re.search(r'opacity\s*:\s*([\d.]+)', decls)
                if m:
                    self.assertGreaterEqual(float(m.group(1)), 0.85, sel)

    def test_touch_target_is_reasonable(self):
        m = re.search(r'\.am-lock-btn\s*\{([^}]*)\}', re.sub(r'/\*.*?\*/', '', self.css, flags=re.S))
        self.assertIsNotNone(m)
        h = re.search(r'min-height:\s*(\d+)px', m.group(1))
        self.assertIsNotNone(h)
        self.assertGreaterEqual(int(h.group(1)), 40)

    def test_mobile_keeps_the_lock_visible(self):
        """The table-first rule hides .am-wrap's children; .am-lock is exempt."""
        mobile = _read(MOBILE_CSS)
        for sel, decls in _css_rules(mobile):
            if '.am-wrap >' in sel and 'display' in decls and 'none' in decls:
                self.assertIn(':not(.am-lock)', sel,
                              'mobile would hide the lock control: %s' % sel.strip())


if __name__ == '__main__':
    unittest.main()
