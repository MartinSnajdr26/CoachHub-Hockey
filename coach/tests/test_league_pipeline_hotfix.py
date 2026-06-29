import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from coach.app import app
from coach.extensions import db
from coach.models import LeagueIntegration, Team
from coach.services.league import service as league_svc
from coach.services.league.base import parse_doc
from coach.services.league.vysledky import VysledkyConnector


URL = 'https://vysledky.com/soutez2.php?id_soutez=19284'

HOCKEY_LAYOUT = """
<html><head><title>Krajská liga mužů 2025/2026</title></head><body>
<h1>Krajská liga mužů 2025/2026</h1>
<table>
  <tr><th>Pořadí</th><th>Z</th><th>V</th><th>VP</th><th>PP</th><th>P</th><th>Skóre</th><th>B</th></tr>
  <tr><td>1.</td><td><img alt="logo"></td><td>HC Baník Příbram B</td><td>18</td><td>13</td><td>0</td><td>0</td><td>5</td><td>104:66</td><td>39</td></tr>
  <tr><td>9.</td><td><img alt="logo"></td><td>HC Smíchov 1913</td><td>18</td><td>6</td><td>3</td><td>1</td><td>8</td><td>86:78</td><td>22</td></tr>
</table>
<table>
  <tr><td>20. kolo</td></tr>
  <tr><td>So 07.02.2026</td><td>HC Smíchov 1913</td><td>HC Kobra Praha B</td><td>4:3 pp</td></tr>
  <tr><td>Ne 08.02.2026</td><td>HC Baník Příbram B</td><td>HC Smíchov 1913</td><td>5:2</td></tr>
</table>
</body></html>
"""


class LeaguePipelineHotfixTest(unittest.TestCase):
    def setUp(self):
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            IS_DEV=False,
        )
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        team = Team(name='HC Smíchov 1913')
        db.session.add(team)
        db.session.commit()
        self.team_id = team.id

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_parser_aligns_hockey_header_to_data_score_column(self):
        data = VysledkyConnector().parse(parse_doc(HOCKEY_LAYOUT), URL)
        row = next(s for s in data.standings if s.team_name == 'HC Smíchov 1913')
        self.assertEqual(row.played, 18)
        self.assertEqual(row.wins, 6)
        self.assertEqual(row.losses, 8)
        self.assertEqual(row.score, '86:78')
        self.assertEqual(row.points, 22)
        self.assertLess(row.points, 999)

        self.assertEqual(len(data.results), 2)
        self.assertEqual(data.results[0].home_team, 'HC Smíchov 1913')
        self.assertEqual(data.results[0].away_team, 'HC Kobra Praha B')
        self.assertTrue(data.results[0].ot)

    def test_refresh_replaces_stale_cache_with_dashboard_readable_json(self):
        league_svc.save_config(self.team_id, True, URL, 'HC Smíchov 1913')
        li = LeagueIntegration.query.filter_by(team_id=self.team_id).first()
        li.data_json = json.dumps({'_schema': 1, 'standings': [], 'results': []})
        db.session.commit()

        with patch('coach.services.league.service.fetch_html_with_meta',
                   return_value=(HOCKEY_LAYOUT, {'bytes': len(HOCKEY_LAYOUT), 'encoding': 'utf-8'})):
            ok, msg = league_svc.refresh(self.team_id, manual=True)
        self.assertTrue(ok, msg)

        db.session.refresh(li)
        cached = json.loads(li.data_json)
        self.assertEqual(cached['_schema'], league_svc.CACHE_SCHEMA)
        self.assertEqual(len(cached['standings']), 2)
        self.assertEqual(cached['standings'][1]['points'], 22)

        view = league_svc.get_view(self.team_id)
        self.assertFalse(view['stale_schema'])
        self.assertEqual(view['team_row']['position'], 9)
        self.assertEqual(view['team_row']['points'], 22)
        self.assertEqual(len(view['results']), 2)
        self.assertTrue(view['form_cards'])


if __name__ == '__main__':
    unittest.main()
