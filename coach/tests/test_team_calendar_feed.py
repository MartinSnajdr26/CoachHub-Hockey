# -*- coding: utf-8 -*-
"""Team calendar subscription feed: lazy token, public feed route, team isolation,
future-only events, stable UIDs, durations, VALARM, attendance link, the
authenticated Dashboard UI, removal of the old single-event UI, and owner-side
feed-token regeneration (which must not touch TeamKey login keys).
"""
import base64
import re
import unittest
from datetime import date, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import (Team, TeamKey, Player, TrainingEvent,
                          TeamCalendarFeedToken)
from coach.services.keys import hash_team_key
from coach.services import calendar_feed

TOKEN_RE = re.compile(r'chhcal_[A-Za-z0-9_-]{20,}')


class _Base(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                          ADMIN_SECRET_KEY='owner-secret', IS_DEV=False)
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.a = Team(name='HC Alpha'); db.session.add(self.a); db.session.flush()
        self.aid = self.a.id
        db.session.add(TeamKey(team_id=self.aid, role='coach', key_hash=hash_team_key('ck')))
        db.session.add(Player(team_id=self.aid, name='Hráč', position='F'))
        # future training + match, and a PAST event that must be excluded
        db.session.add(TrainingEvent(team_id=self.aid, day=date.today() + timedelta(days=3),
                                     time='18:00', title='Trénink; Áčko', kind='training',
                                     source='coachhub_manual'))
        db.session.add(TrainingEvent(team_id=self.aid, day=date.today() + timedelta(days=5),
                                     time='16:00', title='Zápas', kind='match',
                                     source='coachhub_manual'))
        db.session.add(TrainingEvent(team_id=self.aid, day=date.today() - timedelta(days=4),
                                     time='18:00', title='Minulý trénink', kind='training',
                                     source='coachhub_manual'))
        self.b = Team(name='HC Beta'); db.session.add(self.b); db.session.flush()
        self.bid = self.b.id
        db.session.add(TeamKey(team_id=self.bid, role='coach', key_hash=hash_team_key('bk')))
        db.session.add(TrainingEvent(team_id=self.bid, day=date.today() + timedelta(days=2),
                                     time='17:00', title='Beta akce', kind='match',
                                     source='coachhub_manual'))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, tid=None, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = tid or self.aid; s['team_role'] = role; s['team_login'] = True

    def _login_owner(self):
        with self.client.session_transaction() as s:
            s['owner_admin'] = True


class TokenModelTest(_Base):
    def test_token_generated_lazily_and_reused(self):
        self.assertIsNone(calendar_feed.get_active_token(self.aid))
        t1 = calendar_feed.get_or_create_active_token(self.aid)
        self.assertIsNotNone(t1)
        t2 = calendar_feed.get_or_create_active_token(self.aid)
        self.assertEqual(t1.id, t2.id)  # reused, not duplicated
        self.assertEqual(TeamCalendarFeedToken.query.filter_by(team_id=self.aid).count(), 1)

    def test_token_format_and_entropy(self):
        tok = calendar_feed.get_or_create_active_token(self.aid).token
        self.assertTrue(tok.startswith('chhcal_'))
        self.assertRegex(tok, TOKEN_RE)
        # random part decodes to >= 16 bytes (128 bits)
        raw = tok[len('chhcal_'):]
        pad = '=' * (-len(raw) % 4)
        self.assertGreaterEqual(len(base64.urlsafe_b64decode(raw + pad)), 16)

    def test_tokens_unique_across_teams(self):
        ta = calendar_feed.get_or_create_active_token(self.aid).token
        tb = calendar_feed.get_or_create_active_token(self.bid).token
        self.assertNotEqual(ta, tb)


class FeedRouteTest(_Base):
    def _feed(self, token):
        return self.client.get('/calendar/team/%s.ics' % token)

    def test_feed_public_no_login_and_headers(self):
        tok = calendar_feed.get_or_create_active_token(self.aid).token
        r = self._feed(tok)  # no session set
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers['Content-Type'], 'text/calendar; charset=utf-8')

    def test_feed_content_future_only_and_isolated(self):
        tok = calendar_feed.get_or_create_active_token(self.aid).token
        body = self._feed(tok).get_data(as_text=True)
        self.assertIn('BEGIN:VCALENDAR', body)
        self.assertEqual(body.count('BEGIN:VEVENT'), 2)      # 2 future, past excluded
        self.assertNotIn('Minulý trénink', body)             # past event excluded
        self.assertNotIn('Beta akce', body)                  # other team excluded
        # stable UID + durations
        self.assertRegex(body, r'UID:coachhub-event-\d+@coachhubhockey\.com')
        self.assertIn('BEGIN:VALARM', body)
        self.assertIn('TRIGGER:-P1D', body)
        self.assertIn('DTSTART', body); self.assertIn('DTEND', body)
        # attendance link in description
        self.assertRegex(body, r'DESCRIPTION:.*Doch')
        self.assertIn('/attendance', body)
        # Czech chars survive + escaping applied
        self.assertIn('Trénink', body)
        self.assertIn('\\;', body)

    def test_invalid_token_404(self):
        self.assertEqual(self._feed('chhcal_not_a_real_token').status_code, 404)

    def test_rotated_old_token_404_new_token_works(self):
        old = calendar_feed.get_or_create_active_token(self.aid).token
        self.assertEqual(self._feed(old).status_code, 200)
        new_row = calendar_feed.rotate_token(self.aid)
        new = new_row.token
        self.assertNotEqual(old, new)
        self.assertEqual(self._feed(old).status_code, 404)   # old dead
        self.assertEqual(self._feed(new).status_code, 200)   # new works


class DashboardUiTest(_Base):
    def test_dashboard_shows_team_feed_section_not_single_event(self):
        self._login(role='coach')
        h = self.client.get('/app').get_data(as_text=True)
        self.assertIn('Připojit týmový kalendář', h)
        self.assertIn('/calendar/team/', h)
        self.assertIn('Kopírovat odkaz', h)
        # old single-event UI is gone
        self.assertNotIn('Přidat do kalendáře', h)
        self.assertNotIn('dm-hero-cal', h)
        self.assertNotIn('calendar.google.com', h)

    def test_dashboard_shows_only_own_team_token(self):
        # ensure both teams have tokens
        ta = calendar_feed.get_or_create_active_token(self.aid).token
        tb = calendar_feed.get_or_create_active_token(self.bid).token
        self._login(tid=self.aid, role='coach')
        h = self.client.get('/app').get_data(as_text=True)
        self.assertIn(ta, h)
        self.assertNotIn(tb, h)             # never leak another team's token


class OwnerRegenTest(_Base):
    def test_owner_regenerates_feed_without_touching_login_keys(self):
        old = calendar_feed.get_or_create_active_token(self.aid).token
        coach_key_before = TeamKey.query.filter_by(team_id=self.aid, role='coach',
                                                   active=True).first().key_hash
        self._login_owner()
        r = self.client.post('/owner/teams/%d/regenerate-calendar-feed' % self.aid)
        self.assertEqual(r.status_code, 302)
        new = calendar_feed.get_active_token(self.aid).token
        self.assertNotEqual(old, new)
        # old feed dead, new works
        self.assertEqual(self.client.get('/calendar/team/%s.ics' % old).status_code, 404)
        self.assertEqual(self.client.get('/calendar/team/%s.ics' % new).status_code, 200)
        # TeamKey login key untouched
        self.assertEqual(TeamKey.query.filter_by(team_id=self.aid, role='coach',
                                                 active=True).first().key_hash, coach_key_before)

    def test_non_owner_cannot_regenerate_feed(self):
        old = calendar_feed.get_or_create_active_token(self.aid).token
        self._login(role='coach')  # normal team session, not owner
        r = self.client.post('/owner/teams/%d/regenerate-calendar-feed' % self.aid)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/owner/login', r.headers['Location'])
        self.assertEqual(calendar_feed.get_active_token(self.aid).token, old)  # unchanged

    def test_owner_teams_page_still_renders(self):
        self._login_owner()
        h = self.client.get('/owner/teams').get_data(as_text=True)
        self.assertIn('HC Alpha', h)
        self.assertIn('Vygenerovat nový odkaz kalendáře', h)


if __name__ == '__main__':
    unittest.main()
