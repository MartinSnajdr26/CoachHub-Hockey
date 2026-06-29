# -*- coding: utf-8 -*-
"""Pokladna (team payments): coach-only access, status AJAX, amount, history."""
import unittest
from datetime import date

from coach.app import app
from coach.extensions import db
from coach.models import Player, Team, TeamKey, PaymentPeriod, PaymentStatus
from coach.services.keys import hash_team_key


class PokladnaTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.team = Team(name='HC Smíchov'); db.session.add(self.team); db.session.flush()
        self.tid = self.team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        self.players = [Player(team_id=self.tid, name=n, position='F')
                        for n in ('Martin Novák', 'Petr Svoboda', 'Jan Dvořák')]
        db.session.add_all(self.players); db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove(); db.drop_all(); self.ctx.pop()

    def _login(self, role='coach'):
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid; s['team_role'] = role; s['team_login'] = True

    def _period(self):
        return PaymentPeriod.query.filter_by(team_id=self.tid).first()

    # ---- access control ----
    def test_player_cannot_access(self):
        self._login('player')
        self.assertEqual(self.client.get('/pokladna').status_code, 302)

    def test_coach_can_access_and_period_autocreated(self):
        self._login('coach')
        r = self.client.get('/pokladna')
        self.assertEqual(r.status_code, 200)
        h = r.get_data(as_text=True)
        self.assertIn('Pokladna', h)
        self.assertIn('Martin Novák', h)
        self.assertIn('data-wa="payment"', h)
        p = self._period()
        today = date.today()
        self.assertIsNotNone(p)
        self.assertEqual((p.year, p.month), (today.year, today.month))

    # ---- amount ----
    def test_edit_amount(self):
        self._login('coach')
        self.client.get('/pokladna')
        p = self._period()
        self.client.post('/pokladna/amount', data={'period_id': p.id, 'amount': '2500'})
        self.assertEqual(self._period().amount, 2500)

    def test_amount_carries_over_to_next_month(self):
        self._login('coach')
        # seed a prior month with an amount
        prev = PaymentPeriod(team_id=self.tid, year=2026, month=1, amount=2500)
        db.session.add(prev); db.session.commit()
        self.client.get('/pokladna')           # creates current month
        cur = PaymentPeriod.query.filter_by(team_id=self.tid).order_by(
            PaymentPeriod.year.desc(), PaymentPeriod.month.desc()).first()
        self.assertEqual(cur.amount, 2500)     # carried over

    # ---- status AJAX ----
    def test_status_ajax_sets_and_summarizes(self):
        self._login('coach')
        self.client.get('/pokladna')
        p = self._period()
        r = self.client.post('/pokladna/status', json={'period_id': p.id,
                                                        'player_id': self.players[0].id, 'status': 'paid'})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['summary'], {'paid': 1, 'partial': 0, 'unpaid': 2, 'total': 3})
        row = PaymentStatus.query.filter_by(period_id=p.id, player_id=self.players[0].id).first()
        self.assertEqual(row.status, 'paid')

    def test_status_one_player_does_not_affect_others(self):
        self._login('coach')
        self.client.get('/pokladna')
        p = self._period()
        self.client.post('/pokladna/status', json={'period_id': p.id, 'player_id': self.players[0].id, 'status': 'paid'})
        self.client.post('/pokladna/status', json={'period_id': p.id, 'player_id': self.players[1].id, 'status': 'partial'})
        smap = {s.player_id: s.status for s in PaymentStatus.query.filter_by(period_id=p.id).all()}
        self.assertEqual(smap.get(self.players[0].id), 'paid')
        self.assertEqual(smap.get(self.players[1].id), 'partial')
        self.assertIsNone(smap.get(self.players[2].id))     # untouched -> unpaid (no row)

    def test_status_bad_value_rejected(self):
        self._login('coach')
        self.client.get('/pokladna')
        p = self._period()
        r = self.client.post('/pokladna/status', json={'period_id': p.id, 'player_id': self.players[0].id, 'status': 'bogus'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(PaymentStatus.query.count(), 0)

    def test_player_cannot_set_status(self):
        self._login('player')
        # need a period to target
        self._login('coach'); self.client.get('/pokladna'); p = self._period()
        self._login('player')
        r = self.client.post('/pokladna/status', json={'period_id': p.id, 'player_id': self.players[0].id, 'status': 'paid'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(PaymentStatus.query.count(), 0)

    def test_cross_team_player_rejected(self):
        other = Team(name='Other'); db.session.add(other); db.session.flush()
        op = Player(team_id=other.id, name='X', position='F'); db.session.add(op); db.session.commit()
        self._login('coach'); self.client.get('/pokladna'); p = self._period()
        r = self.client.post('/pokladna/status', json={'period_id': p.id, 'player_id': op.id, 'status': 'paid'})
        self.assertEqual(r.status_code, 404)

    # ---- history ----
    def test_history_lists_months(self):
        self._login('coach')
        db.session.add(PaymentPeriod(team_id=self.tid, year=2026, month=7, amount=2500))
        db.session.add(PaymentPeriod(team_id=self.tid, year=2026, month=8, amount=2500))
        db.session.commit()
        h = self.client.get('/pokladna').get_data(as_text=True)
        self.assertIn('Srpen 2026', h)
        self.assertIn('Červenec 2026', h)
        self.assertIn('zaplatilo', h)

    def test_history_month_view(self):
        self._login('coach')
        db.session.add(PaymentPeriod(team_id=self.tid, year=2026, month=7, amount=2500)); db.session.commit()
        r = self.client.get('/pokladna/2026/7')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Červenec 2026', r.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
