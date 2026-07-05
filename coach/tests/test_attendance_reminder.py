# -*- coding: utf-8 -*-
"""WhatsApp attendance reminder feature.

Covers the pure message/inclusion helpers and the coach-only, team-scoped
endpoint (permissions, team isolation, empty state, no DB writes).
"""
import datetime
import unittest
from urllib.parse import unquote

from coach.app import app
from coach.extensions import db
from coach.models import Player, Team, TeamKey, TrainingEvent, AttendanceEntry
from coach.services import attendance_reminder as reminder
from coach.services.keys import hash_team_key


def _P(pid, name):
    return type('P', (), {'id': pid, 'name': name})()


def _E(pid, key, status):
    return type('E', (), {'player_id': pid, 'event_key': key, 'status': status})()


class ReminderHelperTest(unittest.TestCase):
    def setUp(self):
        self.players = [_P(1, 'Ada Novák'), _P(2, 'Bob Svoboda'), _P(3, 'Cyril Dvořák'),
                        _P(4, 'Dan Černý'), _P(5, 'Eda Dlouhé Jméno')]

    # 1/2. unknown + no-record included; 3/4/5. going/not_going/maybe excluded
    def test_inclusion_rule(self):
        entries = [_E(1, 'k', 'going'), _E(2, 'k', 'not_going'), _E(3, 'k', 'maybe'),
                   _E(4, 'k', 'unknown')]  # player 5 has NO record
        names = reminder.unanswered_player_names(self.players, entries, 'k')
        self.assertEqual(names, ['Dan Černý', 'Eda Dlouhé Jméno'])  # only unknown + no-record
        self.assertNotIn('Ada Novák', names)     # going excluded
        self.assertNotIn('Bob Svoboda', names)   # not_going (Ne) excluded
        self.assertNotIn('Cyril Dvořák', names)  # maybe (Možná) excluded

    # 15. order preserved, each player once (no duplicates)
    def test_order_and_no_duplicates(self):
        names = reminder.unanswered_player_names(self.players, [], 'k')  # all unanswered
        self.assertEqual(names, ['Ada Novák', 'Bob Svoboda', 'Cyril Dvořák', 'Dan Černý', 'Eda Dlouhé Jméno'])
        self.assertEqual(len(names), len(set(names)))

    # 7/8/9/11/12. event name, Czech date, time, no location, url
    def test_message_full(self):
        msg = reminder.format_reminder_message('Trénink A', datetime.date(2026, 2, 5), '18:30',
                                               ['Dan Černý'], 'https://host/attendance')
        self.assertIn('Trénink A', msg)              # event name
        self.assertIn('5. 2. 2026', msg)             # Czech date
        self.assertIn('5. 2. 2026 18:30', msg)       # time appended
        self.assertIn('- Dan Černý', msg)
        self.assertIn('https://host/attendance', msg)  # attendance url
        self.assertNotIn('location', msg.lower())    # no location field
        self.assertIn('Děkuji.', msg)

    # 10. missing time omitted cleanly
    def test_message_no_time(self):
        msg = reminder.format_reminder_message('Zápas', datetime.date(2026, 12, 24), '',
                                               ['X'], 'https://h/attendance')
        self.assertIn('24. 12. 2026', msg)
        # the date line is exactly the date (no trailing time / space) when time is missing
        self.assertEqual(msg.split('\n')[3], '24. 12. 2026')

    # 14. Czech characters encoded in the share URL
    def test_wa_url_encodes_czech(self):
        url = reminder.whatsapp_share_url('Dovolím: Černý, Dvořák')
        self.assertTrue(url.startswith('https://wa.me/?text='))
        self.assertNotIn(' ', url)                    # spaces encoded
        self.assertIn('Dovol', unquote(url.split('text=', 1)[1]))  # round-trips back to Czech
        self.assertIn('Černý', unquote(url.split('text=', 1)[1]))


class ReminderEndpointTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC One'); self.other = Team(name='HC Two')
        db.session.add_all([self.team, self.other]); db.session.flush()
        self.tid, self.oid = self.team.id, self.other.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        self.pl = {}
        for n in ['Ada Novák', 'Bob Svoboda', 'Cyril Dvořák', 'Dan Černý', 'Eda Přezdlouhé Jméno Pro Test']:
            p = Player(team_id=self.tid, name=n, position='F'); db.session.add(p); db.session.flush()
            self.pl[n] = p.id
        self.ev = TrainingEvent(team_id=self.tid, day=datetime.date.today(), time='18:00',
                                title='Trénink pondělí', kind='training', source='coachhub_manual')
        # other team's event (for cross-team test)
        self.ev_other = TrainingEvent(team_id=self.oid, day=datetime.date.today(), time='19:00',
                                      title='Cizí trénink', kind='training', source='coachhub_manual')
        db.session.add_all([self.ev, self.ev_other]); db.session.flush()
        self.key = 'local:%d' % self.ev.id
        self.key_other = 'local:%d' % self.ev_other.id
        # responses: Ada=going, Bob=not_going, Cyril=maybe ; Dan=unknown record ; Eda=NO record
        for name, st in [('Ada Novák', 'going'), ('Bob Svoboda', 'not_going'),
                         ('Cyril Dvořák', 'maybe'), ('Dan Černý', 'unknown')]:
            db.session.add(AttendanceEntry(team_id=self.tid, player_id=self.pl[name], event_key=self.key,
                                           status=st, event_day=self.ev.day, event_title=self.ev.title))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach', team_id=None):
        with self.client.session_transaction() as s:
            s['team_id'] = team_id or self.tid; s['team_role'] = role; s['team_login'] = True

    def _wa_text(self, resp):
        self.assertTrue(resp.location.startswith('https://wa.me/?text='), resp.location)
        return unquote(resp.location.split('text=', 1)[1])

    # 17. coach allowed → wa.me with only unanswered players
    def test_coach_reminder_only_unanswered(self):
        self._login('coach')
        r = self.client.get('/attendance/reminder?event=%s' % self.key)
        self.assertEqual(r.status_code, 302)
        text = self._wa_text(r)
        self.assertIn('Trénink pondělí', text)                 # event name
        self.assertIn('- Dan Černý', text)                     # unknown record → included
        self.assertIn('- Eda Přezdlouhé Jméno Pro Test', text) # no record → included
        self.assertNotIn('Ada Novák', text)                    # going excluded
        self.assertNotIn('Bob Svoboda', text)                  # not_going (Ne) excluded
        self.assertNotIn('Cyril Dvořák', text)                 # maybe excluded

    # 12/13. absolute attendance url present, no secrets/keys/ids leaked
    def test_url_present_no_secrets(self):
        self._login('coach')
        text = self._wa_text(self.client.get('/attendance/reminder?event=%s' % self.key))
        self.assertIn('/attendance', text)
        self.assertRegex(text, r'https?://[^/]+/attendance')   # absolute
        for leak in ('team_id', 'session', 'coach_key', 'player_key', 'ck', 'ADMIN', 'secret'):
            self.assertNotIn(leak, text)

    # 16. all answered → no empty WhatsApp; redirect back with the message
    def test_all_answered_no_wa(self):
        for name in self.pl:  # give everyone 'going'
            e = AttendanceEntry.query.filter_by(team_id=self.tid, player_id=self.pl[name], event_key=self.key).first()
            if e:
                e.status = 'going'
            else:
                db.session.add(AttendanceEntry(team_id=self.tid, player_id=self.pl[name], event_key=self.key,
                                               status='going', event_day=self.ev.day, event_title=self.ev.title))
        db.session.commit()
        self._login('coach')
        r = self.client.get('/attendance/reminder?event=%s' % self.key)
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('wa.me', r.location)                  # did NOT open WhatsApp

    # 18. player-only denied (never reaches wa.me / list)
    def test_player_denied(self):
        self._login('player')
        r = self.client.get('/attendance/reminder?event=%s' % self.key)
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('wa.me', r.location or '')

    # 19. cross-team denied (coach of team One cannot reminder team Two's event)
    def test_cross_team_denied(self):
        self._login('coach', team_id=self.tid)
        r = self.client.get('/attendance/reminder?event=%s' % self.key_other)
        self.assertEqual(r.status_code, 404)

    def test_missing_or_unknown_event_404(self):
        self._login('coach')
        self.assertEqual(self.client.get('/attendance/reminder').status_code, 404)
        self.assertEqual(self.client.get('/attendance/reminder?event=local:99999').status_code, 404)

    # 20. no DB rows created/changed by generating a reminder
    def test_no_db_writes(self):
        before = AttendanceEntry.query.count()
        self._login('coach')
        self.client.get('/attendance/reminder?event=%s' % self.key)
        self.assertEqual(AttendanceEntry.query.count(), before)


if __name__ == '__main__':
    unittest.main()
