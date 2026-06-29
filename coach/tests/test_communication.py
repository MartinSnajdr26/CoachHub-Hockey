# -*- coding: utf-8 -*-
"""Communication 2.0 (Nástěnka): posting, roles, reactions, edit/delete window,
backward compatibility, XSS escaping."""
import json
import unittest
from datetime import datetime, timedelta

from coach.app import app
from coach.extensions import db
from coach.models import AuditEvent, Team, TeamKey
from coach.services.keys import hash_team_key


class CommunicationTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Test'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='player'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    def _msgs(self):
        return AuditEvent.query.filter_by(team_id=self.tid, event='message').all()

    def _meta(self, ev):
        return json.loads(ev.meta or '{}')

    # ---- access ----
    def test_requires_login(self):
        self.assertIn(self.client.get('/nastenka').status_code, (302, 401))

    def test_feed_renders(self):
        self._login('coach')
        h = self.client.get('/nastenka').get_data(as_text=True)
        self.assertEqual(self.client.get('/nastenka').status_code, 200)
        self.assertIn('Nástěnka', h)
        self.assertIn('id="cm-composer"', h)
        self.assertIn('id="cm-search"', h)

    # ---- posting ----
    def test_player_can_post_with_nickname_and_category(self):
        self._login('player')
        self.client.post('/nastenka/post', data={'text': 'Ahoj tým', 'nickname': 'Kuba #17',
                                                  'category': 'question', 'token': 't1', 'pub': 'p1'})
        msgs = self._msgs()
        self.assertEqual(len(msgs), 1)
        m = self._meta(msgs[0])
        self.assertEqual(m['text'], 'Ahoj tým')
        self.assertEqual(m['nickname'], 'Kuba #17')
        self.assertEqual(m['category'], 'question')
        self.assertEqual(m['token'], 't1')

    def test_player_cannot_pin_or_mark_important_on_post(self):
        self._login('player')
        self.client.post('/nastenka/post', data={'text': 'x', 'pinned': 'on', 'important': 'on'})
        m = self._meta(self._msgs()[0])
        self.assertFalse(m['pinned'])
        self.assertFalse(m['important'])

    def test_bad_category_defaults_general(self):
        self._login('player')
        self.client.post('/nastenka/post', data={'text': 'x', 'category': 'bogus'})
        self.assertEqual(self._meta(self._msgs()[0])['category'], 'general')

    def test_length_validation(self):
        self._login('player')
        self.client.post('/nastenka/post', data={'text': 'a' * 999, 'nickname': 'n' * 99})
        m = self._meta(self._msgs()[0])
        self.assertEqual(len(m['text']), 500)
        self.assertEqual(len(m['nickname']), 30)

    def test_empty_text_not_posted(self):
        self._login('player')
        self.client.post('/nastenka/post', data={'text': '   '})
        self.assertEqual(len(self._msgs()), 0)

    # ---- coach moderation ----
    def test_coach_pin_and_important(self):
        self._login('coach')
        self.client.post('/nastenka/post', data={'text': 'x'})
        mid = self._msgs()[0].id
        self.client.post('/nastenka/pin/%d' % mid)
        self.client.post('/nastenka/important/%d' % mid)
        m = self._meta(AuditEvent.query.get(mid))
        self.assertTrue(m['pinned'] and m['important'])

    def test_player_cannot_pin(self):
        self._login('coach'); self.client.post('/nastenka/post', data={'text': 'x'})
        mid = self._msgs()[0].id
        self._login('player')
        self.client.post('/nastenka/pin/%d' % mid)
        self.assertFalse(self._meta(AuditEvent.query.get(mid))['pinned'])

    def test_coach_can_delete_any(self):
        self._login('player'); self.client.post('/nastenka/post', data={'text': 'x', 'token': 't', 'pub': 'p'})
        mid = self._msgs()[0].id
        self._login('coach')
        self.client.post('/nastenka/delete/%d' % mid)
        self.assertEqual(len(self._msgs()), 0)

    # ---- player ownership window ----
    def test_player_edit_own_with_token(self):
        self._login('player')
        self.client.post('/nastenka/post', data={'text': 'orig', 'token': 'secret', 'pub': 'p'})
        mid = self._msgs()[0].id
        self.client.post('/nastenka/edit/%d' % mid, data={'text': 'edited', 'token': 'secret'})
        self.assertEqual(self._meta(AuditEvent.query.get(mid))['text'], 'edited')

    def test_player_edit_wrong_token_rejected(self):
        self._login('player')
        self.client.post('/nastenka/post', data={'text': 'orig', 'token': 'secret', 'pub': 'p'})
        mid = self._msgs()[0].id
        self.client.post('/nastenka/edit/%d' % mid, data={'text': 'hax', 'token': 'wrong'})
        self.assertEqual(self._meta(AuditEvent.query.get(mid))['text'], 'orig')

    def test_player_delete_after_window_rejected(self):
        self._login('player')
        self.client.post('/nastenka/post', data={'text': 'x', 'token': 'secret', 'pub': 'p'})
        ev = self._msgs()[0]
        ev.created_at = datetime.utcnow() - timedelta(minutes=20)   # past 15-min window
        db.session.commit()
        self.client.post('/nastenka/delete/%d' % ev.id, data={'token': 'secret'})
        self.assertEqual(len(self._msgs()), 1)                      # still there

    # ---- reactions ----
    def test_reaction_add_switch_remove(self):
        self._login('player')
        self.client.post('/nastenka/post', data={'text': 'x'})
        mid = self._msgs()[0].id
        r = self.client.post('/nastenka/react/%d' % mid, json={'reaction': 'like', 'prev': ''})
        self.assertEqual(r.get_json()['reactions']['like'], 1)
        # switch like -> thanks
        r = self.client.post('/nastenka/react/%d' % mid, json={'reaction': 'thanks', 'prev': 'like'})
        j = r.get_json()['reactions']
        self.assertEqual(j['like'], 0); self.assertEqual(j['thanks'], 1)
        # remove thanks
        r = self.client.post('/nastenka/react/%d' % mid, json={'reaction': '', 'prev': 'thanks'})
        self.assertEqual(r.get_json()['reactions']['thanks'], 0)

    def test_bad_reaction_rejected(self):
        self._login('player'); self.client.post('/nastenka/post', data={'text': 'x'})
        mid = self._msgs()[0].id
        r = self.client.post('/nastenka/react/%d' % mid, json={'reaction': 'rage'})
        self.assertEqual(r.status_code, 400)

    # ---- backward compatibility ----
    def test_legacy_message_renders(self):
        # legacy meta lacks category/nickname/reactions
        db.session.add(AuditEvent(event='message', team_id=self.tid, role='coach',
                                  meta=json.dumps({'text': 'Stará zpráva', 'role': 'coach', 'pinned': True})))
        db.session.commit()
        self._login('coach')
        h = self.client.get('/nastenka').get_data(as_text=True)
        self.assertIn('Stará zpráva', h)
        self.assertIn('Obecné', h)            # defaulted category badge
        self.assertIn('Připnuto', h)          # legacy pinned respected

    # ---- XSS ----
    def test_xss_escaped(self):
        self._login('player')
        self.client.post('/nastenka/post', data={'text': '<script>alert(1)</script>'})
        h = self.client.get('/nastenka').get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', h)
        self.assertIn('&lt;script&gt;', h)


if __name__ == '__main__':
    unittest.main()
