"""Regression tests for removing a player from a team (`POST /delete_player/<id>`).

Desktop (`templates/players.html`) and mobile (`templates/mobile/_players.html`)
both post plain forms to this one route, so a backend failure breaks both. The
bug these cover: `delete_player` cleaned up Roster / LineAssignment /
AttendanceEntry but NOT PaymentStatus (Pokladna), which also carries a
`FOREIGN KEY -> player.id`. Deleting a player who had any payment row therefore
violated the constraint and returned HTTP 500 on production MySQL/InnoDB (and
left orphaned rows on SQLite, where foreign keys are not enforced).
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from coach.app import app
from coach.extensions import db
from coach.models import (
    AttendanceEntry,
    LineAssignment,
    PaymentPeriod,
    PaymentStatus,
    Player,
    Roster,
    Team,
)


def _tables_referencing_player():
    """Every (table, column) in the schema with a FK to ``player.id``.

    Derived from the metadata so a future model that gains a player FK without a
    matching cleanup in `delete_player` fails these tests instead of production.
    """
    refs = []
    for table in db.metadata.tables.values():
        for col in table.columns:
            for fk in col.foreign_keys:
                if fk.target_fullname == 'player.id':
                    refs.append((table, col))
    return refs


class PlayerRemovalTest(unittest.TestCase):
    def setUp(self):
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        )
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

        self.team = Team(name='Alpha')
        self.other_team = Team(name='Beta')
        db.session.add_all([self.team, self.other_team])
        db.session.commit()

        self.player = Player(team_id=self.team.id, name='Jan Novák', position='F')
        self.teammate = Player(team_id=self.team.id, name='Petr Svoboda', position='D')
        self.foreign_player = Player(team_id=self.other_team.id, name='Beta Hráč', position='G')
        db.session.add_all([self.player, self.teammate, self.foreign_player])
        db.session.commit()

        self.client = app.test_client()
        self._login('coach')

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    # -- helpers ---------------------------------------------------------
    def _login(self, role, team_id=None):
        with self.client.session_transaction() as sess:
            sess['team_id'] = team_id or self.team.id
            sess['team_role'] = role
            sess['team_login'] = True

    def _seed_related_rows(self, player):
        """One row in every table that references the player."""
        period = PaymentPeriod.query.filter_by(team_id=player.team_id, year=2026, month=6).first()
        if period is None:
            period = PaymentPeriod(team_id=player.team_id, year=2026, month=6, amount=500)
            db.session.add(period)
            db.session.commit()
        db.session.add_all([
            Roster(team_id=player.team_id, player_id=player.id),
            LineAssignment(team_id=player.team_id, player_id=player.id, slot='L1LW'),
            AttendanceEntry(
                team_id=player.team_id,
                player_id=player.id,
                event_key='local:1',
                event_title='Trénink',
                event_day=date(2026, 6, 28),
                status='going',
            ),
            PaymentStatus(team_id=player.team_id, period_id=period.id, player_id=player.id, status='paid'),
        ])
        db.session.commit()

    def _rows_referencing(self, player_id):
        total = 0
        for table, col in _tables_referencing_player():
            total += db.session.execute(
                db.select(db.func.count()).select_from(table).where(col == player_id)
            ).scalar_one()
        return total

    # -- successful authorized removal -----------------------------------
    def test_delete_player_removes_every_referencing_row(self):
        self._seed_related_rows(self.player)
        # Guard: the fixture really does exercise all FK tables.
        self.assertEqual(self._rows_referencing(self.player.id), len(_tables_referencing_player()))

        res = self.client.post(f'/delete_player/{self.player.id}')

        self.assertEqual(res.status_code, 302)
        self.assertIsNone(db.session.get(Player, self.player.id))
        self.assertEqual(self._rows_referencing(self.player.id), 0,
                         'orphaned rows left behind by delete_player')

    def test_delete_player_removes_payment_status(self):
        """The specific row type that used to be missed (Pokladna)."""
        self._seed_related_rows(self.player)
        self.assertEqual(PaymentStatus.query.filter_by(player_id=self.player.id).count(), 1)

        res = self.client.post(f'/delete_player/{self.player.id}')

        self.assertEqual(res.status_code, 302)
        self.assertEqual(PaymentStatus.query.filter_by(player_id=self.player.id).count(), 0)

    def test_delete_player_succeeds_with_foreign_keys_enforced(self):
        """Mirror production MySQL/InnoDB, where the FK is actually enforced.

        SQLite leaves foreign keys off by default, so without this PRAGMA the
        original bug looked like a success locally and only 500'd on the server.
        """
        self._seed_related_rows(self.player)
        db.session.commit()          # no open transaction: PRAGMA is a no-op inside one
        db.session.execute(db.text('PRAGMA foreign_keys=ON'))
        self.assertEqual(
            db.session.execute(db.text('PRAGMA foreign_keys')).scalar(), 1,
            'could not enable SQLite FK enforcement for this test',
        )
        try:
            res = self.client.post(f'/delete_player/{self.player.id}')
            self.assertEqual(res.status_code, 302, 'FK violation — dependent rows were not cleared')
            self.assertIsNone(db.session.get(Player, self.player.id))
        finally:
            db.session.execute(db.text('PRAGMA foreign_keys=OFF'))

    def test_delete_player_leaves_other_players_untouched(self):
        self._seed_related_rows(self.player)
        self._seed_related_rows(self.teammate)

        self.client.post(f'/delete_player/{self.player.id}')

        self.assertIsNotNone(db.session.get(Player, self.teammate.id))
        self.assertEqual(self._rows_referencing(self.teammate.id), len(_tables_referencing_player()))

    def test_delete_player_is_idempotent_on_repeat_submit(self):
        """Double-submit (impatient tap / retry) must not 500 on the second POST."""
        self._seed_related_rows(self.player)
        first = self.client.post(f'/delete_player/{self.player.id}')
        second = self.client.post(f'/delete_player/{self.player.id}')
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Player.query.filter_by(team_id=self.team.id).count(), 1)

    # -- authorization ---------------------------------------------------
    def test_delete_player_rejects_other_teams_player(self):
        """A hand-edited player id must not reach across teams."""
        self._seed_related_rows(self.foreign_player)

        res = self.client.post(f'/delete_player/{self.foreign_player.id}')

        self.assertEqual(res.status_code, 302)
        self.assertIsNotNone(db.session.get(Player, self.foreign_player.id))
        self.assertEqual(self._rows_referencing(self.foreign_player.id),
                         len(_tables_referencing_player()))

    def test_delete_player_rejects_player_role(self):
        self._login('player')
        res = self.client.post(f'/delete_player/{self.player.id}')
        self.assertEqual(res.status_code, 302)
        self.assertIsNotNone(db.session.get(Player, self.player.id))

    def test_delete_player_rejects_anonymous(self):
        anon = app.test_client()
        res = anon.post(f'/delete_player/{self.player.id}')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/team/auth', res.headers.get('Location', ''))
        self.assertIsNotNone(db.session.get(Player, self.player.id))

    def test_delete_player_rejects_unknown_id(self):
        res = self.client.post('/delete_player/999999')
        self.assertEqual(res.status_code, 302)
        self.assertEqual(Player.query.count(), 3)

    def test_delete_player_rejects_get(self):
        res = self.client.get(f'/delete_player/{self.player.id}')
        self.assertEqual(res.status_code, 405)
        self.assertIsNotNone(db.session.get(Player, self.player.id))

    def test_delete_player_requires_csrf_token(self):
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            res = self.client.post(f'/delete_player/{self.player.id}')
            self.assertEqual(res.status_code, 400)
            self.assertIsNotNone(db.session.get(Player, self.player.id))
        finally:
            app.config['WTF_CSRF_ENABLED'] = False


class PlayerRemovalMarkupTest(unittest.TestCase):
    """Desktop and mobile must both offer removal through the same route.

    Each row owns its own <form action="/delete_player/<id>"> — there is no
    shared confirmation modal, so switching between players cannot carry a stale
    player id into the request.
    """

    def setUp(self):
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        )
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.team = Team(name='Alpha')
        db.session.add(self.team)
        db.session.commit()
        self.players = [
            Player(team_id=self.team.id, name='Jan Novák', position='F'),
            Player(team_id=self.team.id, name='Petr Svoboda', position='D'),
            Player(team_id=self.team.id, name='Tomáš Brankář', position='G'),
        ]
        db.session.add_all(self.players)
        db.session.commit()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _get_players_page(self, role='coach'):
        with self.client.session_transaction() as sess:
            sess['team_id'] = self.team.id
            sess['team_role'] = role
            sess['team_login'] = True
        res = self.client.get('/players')
        self.assertEqual(res.status_code, 200)
        return res.get_data(as_text=True)

    def test_every_player_has_a_delete_form_on_both_layouts(self):
        html = self._get_players_page()
        for p in self.players:
            action = f'action="/delete_player/{p.id}"'
            # one desktop form (position column) + one mobile card form
            self.assertEqual(html.count(action), 2,
                             f'expected desktop+mobile delete forms for player {p.id}')

    def test_delete_forms_post_with_csrf_token(self):
        html = self._get_players_page()
        for chunk in html.split('action="/delete_player/')[1:]:
            form = chunk.split('</form>')[0]
            self.assertIn('method="POST"', form)
            self.assertIn('name="csrf_token"', form)
            self.assertIn('type="submit"', form)

    def test_mobile_card_uses_the_shared_confirm_convention(self):
        html = self._get_players_page()
        self.assertIn('class="plm-del form-confirm"', html)      # mobile: form-level confirm
        self.assertIn('class="btn-confirm"', html)               # desktop: button-level confirm
        self.assertIn('Opravdu smazat hráče Jan Novák?', html)

    def test_mobile_card_hides_delete_from_player_role(self):
        """Mobile gates the card actions behind `is_coach`.

        The desktop layout does NOT gate its delete forms (pre-existing, frozen
        markup) — a player-role session still sees the ❌ buttons there. That is
        cosmetic only: `coach_required` rejects the POST server-side, which
        `PlayerRemovalTest.test_delete_player_rejects_player_role` pins down.
        """
        html = self._get_players_page(role='player')
        self.assertNotIn('class="plm-del form-confirm"', html)
        self.assertNotIn('plm-act--danger', html)


if __name__ == '__main__':
    unittest.main()
