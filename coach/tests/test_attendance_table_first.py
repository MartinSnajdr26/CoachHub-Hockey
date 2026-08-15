# -*- coding: utf-8 -*-
"""Table-first coach attendance + the personalised verified-player welcome.

Two UX changes, one behavioural contract each:

  1. /dochazka ships TABLE-FIRST. The coach lands in the matrix with no view to
     choose; the mobile "Akce"/"Hráči" views are switched off, NOT deleted, so
     `calendar.ATTENDANCE_VIEW_SWITCHER = True` must bring them straight back.
  2. The dashboard greets a passkey-VERIFIED player by name, resolved
     server-side from `session['player_id']`. Coaches, shared-key sessions and
     stale player rows must never produce a name (or a 500).
"""
import unittest
from datetime import date, timedelta

from coach.app import app
from coach.blueprints import calendar as calendar_bp
from coach.extensions import db
from coach.models import AttendanceEntry, Player, Team, TeamKey, TrainingEvent
from coach.services.keys import hash_team_key
from coach.tests.session_helpers import login_session, login_shared_key_session


class TableFirstBase(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                          ADMIN_SECRET_KEY='owner-secret')
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

        self.team = Team(name='HC Test')
        db.session.add(self.team)
        db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach',
                               key_hash=hash_team_key('coach-key')))
        db.session.add(TeamKey(team_id=self.tid, role='player',
                               key_hash=hash_team_key('player-key')))

        self.player = Player(team_id=self.tid, name='Martin Šnajdr', position='F')
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

    def _get_dochazka(self):
        resp = self.client.get('/dochazka')
        self.assertEqual(resp.status_code, 200)
        return resp.get_data(as_text=True)


class CoachAttendanceIsTableFirstTest(TableFirstBase):
    """§1 — the coach lands in Tabulka, with no Akce/Hráči controls."""

    def setUp(self):
        super().setUp()
        login_session(self.client, self.tid, 'coach')

    def test_matrix_is_rendered_on_the_first_request(self):
        """No second request, no ?view= round-trip: the grid is in the HTML."""
        html = self._get_dochazka()
        self.assertIn('id="am-grid"', html)
        self.assertIn('am-cell', html)

    def test_no_active_akce_or_hraci_controls(self):
        """The three-way switcher must not be in the delivered markup at all."""
        html = self._get_dochazka()
        self.assertNotIn('data-tam-view', html)
        self.assertNotIn('tam-seg-btn', html)
        self.assertNotIn('>Akce<', html)
        self.assertNotIn('>Hráči<', html)
        # ...nor the sections those tabs used to reveal.
        self.assertNotIn('data-view="akce"', html)
        self.assertNotIn('data-view="hraci"', html)

    def test_mobile_root_requests_the_table_only_layout(self):
        """The CSS hook that reveals .am-wrap on mobile without any JS."""
        html = self._get_dochazka()
        self.assertIn('tam-root--table-only', html)

    def test_table_editing_still_works_for_the_coach(self):
        """Table-first must not have cost the matrix its write path."""
        resp = self.client.post('/attendance/cell', json={
            'player_id': self.pid, 'event_key': self.ev_key, 'status': 'going'})
        self.assertEqual(resp.status_code, 200)
        entry = AttendanceEntry.query.filter_by(
            team_id=self.tid, player_id=self.pid, event_key=self.ev_key).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, 'going')

    def test_matrix_cells_are_enabled_for_a_coach(self):
        html = self._get_dochazka()
        self.assertIn('data-key="%s"' % self.ev_key, html)
        self.assertNotIn('disabled aria-label', html)

    def test_range_filter_still_navigates(self):
        """The one control kept on mobile still round-trips through the route."""
        html = self.client.get('/dochazka?range=all').get_data(as_text=True)
        self.assertIn('tam-chip', html)
        self.assertIn('is-active', html)

    def test_empty_period_shows_an_empty_state_not_a_scroll_hint(self):
        """With no matrix to scroll, mobile must not point at nothing."""
        TrainingEvent.query.filter_by(team_id=self.tid).delete()
        db.session.commit()
        html = self.client.get('/dochazka?range=future').get_data(as_text=True)
        self.assertIn('tam-empty', html)
        self.assertNotIn('posuň ji do stran', html)


class ViewSwitcherIsDeactivatedNotDeletedTest(TableFirstBase):
    """§2 — deactivation must be a flag, so the work can be restored."""

    def setUp(self):
        super().setUp()
        login_session(self.client, self.tid, 'coach')

    def test_flag_is_off_by_default(self):
        self.assertFalse(calendar_bp.ATTENDANCE_VIEW_SWITCHER)

    def test_flipping_the_flag_restores_both_views(self):
        """The Akce/Hráči implementation is still present and still wired up."""
        original = calendar_bp.ATTENDANCE_VIEW_SWITCHER
        calendar_bp.ATTENDANCE_VIEW_SWITCHER = True
        try:
            html = self._get_dochazka()
            self.assertIn('data-tam-view="akce"', html)
            self.assertIn('data-tam-view="hraci"', html)
            self.assertIn('data-tam-view="tabulka"', html)
            self.assertIn('data-view="akce"', html)
            self.assertIn('data-view="hraci"', html)
            self.assertIn('tamPlayerSheet', html)          # detail sheet + its JS
            self.assertNotIn('tam-root--table-only', html)
        finally:
            calendar_bp.ATTENDANCE_VIEW_SWITCHER = original


class PlayerAttendanceUnaffectedTest(TableFirstBase):
    """§3 — the verified-player workflow must not be routed into the matrix."""

    def test_verified_player_keeps_their_own_page(self):
        login_session(self.client, self.tid, 'player', player_id=self.pid)
        resp = self.client.get('/attendance')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Martin Šnajdr', resp.get_data(as_text=True))

    def test_verified_player_cannot_write_through_the_coach_cell_endpoint(self):
        login_session(self.client, self.tid, 'player', player_id=self.pid)
        resp = self.client.post('/attendance/cell', json={
            'player_id': self.pid, 'event_key': self.ev_key, 'status': 'going'})
        self.assertNotEqual(resp.status_code, 200)

    def test_shared_key_session_still_bounces_to_onboarding(self):
        login_shared_key_session(self.client, self.tid)
        resp = self.client.get('/dochazka')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/player/onboarding', resp.headers['Location'])


class VerifiedPlayerWelcomeTest(TableFirstBase):
    """§4-6 — the greeting is presentation data resolved from player_id."""

    def _home(self):
        resp = self.client.get('/app')
        self.assertEqual(resp.status_code, 200)
        return resp.get_data(as_text=True)

    def test_verified_player_is_greeted_by_name(self):
        login_session(self.client, self.tid, 'player', player_id=self.pid)
        html = self._home()
        self.assertIn('Martin Šnajdr', html)
        self.assertIn('Vítej zpět, Martin Šnajdr', html)      # desktop hero
        self.assertIn('Dobrý den, Martin Šnajdr', html)       # mobile greeting

    def test_coach_gets_the_generic_welcome(self):
        login_session(self.client, self.tid, 'coach')
        html = self._home()
        self.assertIn('Vítej zpět', html)
        self.assertNotIn('Vítej zpět,', html)
        self.assertNotIn('Dobrý den,', html)

    def test_shared_key_session_cannot_reach_the_homepage(self):
        login_shared_key_session(self.client, self.tid)
        resp = self.client.get('/app')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/player/onboarding', resp.headers['Location'])

    def test_stale_player_id_falls_back_instead_of_crashing(self):
        """A session pointing at a deleted roster row must not 500."""
        login_session(self.client, self.tid, 'player', player_id=self.pid)
        Player.query.filter_by(id=self.pid).delete()
        db.session.commit()
        html = self._home()
        self.assertIn('Vítej zpět', html)
        self.assertNotIn('Vítej zpět,', html)

    def test_name_is_not_resolved_across_teams(self):
        """player_id from another team must not leak that team's roster name."""
        other = Team(name='HC Other')
        db.session.add(other)
        db.session.flush()
        foreign = Player(team_id=other.id, name='Cizí Hráč', position='D')
        db.session.add(foreign)
        db.session.commit()
        login_session(self.client, self.tid, 'player', player_id=foreign.id)
        html = self._home()
        self.assertNotIn('Cizí Hráč', html)
        self.assertNotIn('Vítej zpět,', html)

    def test_name_is_never_taken_from_the_request(self):
        """Query string / form data must not be able to set the greeting."""
        login_session(self.client, self.tid, 'coach')
        html = self.client.get(
            '/app?player_name=Podvod&name=Podvod').get_data(as_text=True)
        self.assertNotIn('Podvod', html)

    def test_name_is_escaped(self):
        """Player.name is roster free-text; it must not reach the DOM raw."""
        self.player.name = '<script>x</script>'
        db.session.commit()
        login_session(self.client, self.tid, 'player', player_id=self.pid)
        html = self._home()
        self.assertNotIn('<script>x</script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_helper_returns_none_for_non_player_sessions(self):
        """Unit-level check of the resolver's fail-safe branches."""
        login_session(self.client, self.tid, 'coach')
        with self.client.session_transaction():
            pass
        with app.test_request_context('/app'):
            from flask import session as s
            s['team_id'] = self.tid
            s['team_role'] = 'coach'
            s['team_login'] = True
            s['auth_method'] = 'team_key'
            self.assertIsNone(calendar_bp._verified_player_name(self.tid))


if __name__ == '__main__':
    unittest.main()
