# -*- coding: utf-8 -*-
"""Parser tests for the league integration, using a representative
vysledky.com `soutez2.php` HTML sample (Windows-1250, logo cells, a team
name that contains a number, header row, and weekday+time in results)."""
from coach.services.league.base import decode_html, parse_doc
from coach.services.league import get_connector
from coach.services.league.vysledky import VysledkyConnector
from coach.services.league.generic_html import GenericHtmlTableConnector


# Representative classic vysledky.com page (served as Windows-1250).
SAMPLE = (
    "<html><head>"
    "<meta http-equiv='Content-Type' content='text/html; charset=windows-1250'>"
    "<title>Krajská liga mužů - Ústecký kraj | vysledky.com</title>"
    "<script>var ad=1;</script>"
    "</head><body>"
    "<form action='login.php'><input name='u'></form>"
    "<h1>Krajská liga mužů 2025/2026</h1><h2>Ústecký kraj</h2>"
    "<table>"  # nested layout wrapper
    "<tr><td>"
    "<table class='tabulka'>"
    "<tr><th>#</th><th></th><th>Tým</th><th>Z</th><th>V</th><th>R</th><th>P</th><th>Skóre</th><th>B</th><th>+/-</th></tr>"
    "<tr><td>8.</td><td><img src='a.gif' alt='logo'></td><td>HC Roudnice</td><td>18</td><td>7</td><td>2</td><td>9</td><td>70:72</td><td>23</td><td>-2</td></tr>"
    "<tr><td>9.</td><td><img src='b.gif' alt='logo'></td><td>HC Smíchov 1913</td><td>18</td><td>6</td><td>3</td><td>9</td><td>86:78</td><td>22</td><td>-5</td></tr>"
    "<tr><td>10.</td><td><img src='c.gif' alt='logo'></td><td>SK Žebrák 02</td><td>18</td><td>5</td><td>1</td><td>12</td><td>60:95</td><td>16</td><td>-35</td></tr>"
    "</table>"
    "<table>"  # results
    "<tr><td colspan='6'>20. kolo</td></tr>"
    "<tr><td>So 07.02.2026 17:45</td><td><img alt='logo'></td><td>Žebrák</td><td>4:3</td><td><img alt='logo'></td><td>Smíchov</td></tr>"
    "<tr><td>Ne 08.02.2026 10:00</td><td><img alt='logo'></td><td>HC Smíchov 1913</td><td>2:5</td><td><img alt='logo'></td><td>HC Roudnice</td></tr>"
    "</table>"
    "</td></tr></table>"
    "</body></html>"
)

URL = "https://vysledky.com/soutez2.php?id_soutez=19716"


def _parse(sample=SAMPLE, charset='windows-1250'):
    raw = sample.encode('cp1250')
    txt = decode_html(raw, 'text/html; charset=%s' % charset)
    conn = get_connector(URL)
    return conn, conn.parse(parse_doc(txt), URL)


def test_connector_selected_is_vysledky():
    conn, _ = _parse()
    assert isinstance(conn, VysledkyConnector)


def test_windows1250_decoded():
    raw = SAMPLE.encode('cp1250')
    txt = decode_html(raw, 'text/html; charset=windows-1250')
    assert 'Smíchov' in txt and 'Ústecký' in txt and 'Žebrák' in txt


def test_competition_info():
    _, data = _parse()
    assert 'Krajská liga' in data.info.competition_name
    assert data.info.season == '2025/2026'
    assert 'kraj' in data.info.region.lower()


def test_team_name_with_number_kept_whole():
    _, data = _parse()
    row = next(s for s in data.standings if s.team_name.startswith('HC Smíchov'))
    assert row.team_name == 'HC Smíchov 1913'   # 1913 is NOT a stat


def test_standings_row_values():
    _, data = _parse()
    row = next(s for s in data.standings if s.team_name == 'HC Smíchov 1913')
    assert row.position == 9
    assert row.played == 18
    assert row.wins == 6
    assert row.draws == 3
    assert row.losses == 9
    assert row.score == '86:78'          # colon preserved
    assert row.goals_for == 86
    assert row.goals_against == 78
    assert row.points == 22              # from B column, NOT score, NOT last int
    assert row.plus_minus == -5          # from +/- column, not gf-ga (would be +8)


def test_points_not_corrupted_by_score():
    _, data = _parse()
    for s in data.standings:
        assert s.points < 100            # never the merged score like 8678
        assert ':' not in str(s.points)


def test_recent_results_both_teams():
    _, data = _parse()
    first = data.results[0]
    assert first.home_team == 'Žebrák'
    assert first.away_team == 'Smíchov'      # away NOT dropped
    assert first.home_score == 4 and first.away_score == 3
    assert (first.date or '').startswith('So 07.02.2026')
    assert first.round == '20. kolo'


def test_results_team_with_number_kept():
    _, data = _parse()
    r = next(r for r in data.results if r.home_team == 'HC Smíchov 1913')
    assert r.away_team == 'HC Roudnice'
    assert r.home_score == 2 and r.away_score == 5


def test_time_cell_not_mistaken_for_score():
    """A separate time cell (17:45) and an OT score in one fragment: time is not
    a score (no team both sides), away team kept, OT flagged."""
    frag = (
        "<html><body><table>"
        "<tr><td>So 07.02.2026</td><td>17:45</td><td>Žebrák</td><td>4:3 pp</td><td>Smíchov</td></tr>"
        "</table></body></html>"
    )
    conn = GenericHtmlTableConnector()
    data = conn.parse(parse_doc(decode_html(frag.encode('cp1250'), 'charset=windows-1250')), URL)
    assert len(data.results) == 1
    r = data.results[0]
    assert r.home_team == 'Žebrák' and r.away_team == 'Smíchov'
    assert r.home_score == 4 and r.away_score == 3
    assert r.ot is True


def test_form_codes_have_no_draw():
    from coach.services.league import service as svc
    # Smíchov: away L (3<4), home L (2<5), an OT loss, an OT win -> L,L,OL,OW (no D)
    results = [
        {'home_team': 'Žebrák', 'away_team': 'Smíchov', 'home_score': 4, 'away_score': 3, 'ot': False},
        {'home_team': 'HC Smíchov 1913', 'away_team': 'HC Roudnice', 'home_score': 2, 'away_score': 5, 'ot': False},
        {'home_team': 'Smíchov', 'away_team': 'Most', 'home_score': 3, 'away_score': 4, 'ot': True},
        {'home_team': 'Teplice', 'away_team': 'HC Smíchov 1913', 'home_score': 2, 'away_score': 3, 'ot': True},
        {'home_team': 'Smíchov', 'away_team': 'Bílina', 'home_score': 3, 'away_score': 3, 'ot': False},  # tie -> skipped
    ]
    codes = [svc._result_code(r, 'HC Smíchov 1913') for r in results]
    codes = [c for c in codes if c]
    assert 'D' not in codes
    assert codes == ['L', 'L', 'OL', 'OW']


def test_no_header_anchored_fallback():
    """Same standings data but WITHOUT a header row -> anchored parser must still
    read columns correctly (Z/V/R/P before skóre, B/± after), team text intact."""
    no_hdr = (
        "<html><head><title>Liga | vysledky.com</title></head><body><h1>Liga</h1>"
        "<table>"
        "<tr><td>9.</td><td><img alt='logo'></td><td>HC Smíchov 1913</td><td>18</td><td>6</td><td>3</td><td>9</td><td>86:78</td><td>22</td><td>-5</td></tr>"
        "<tr><td>10.</td><td><img alt='logo'></td><td>SK Žebrák 02</td><td>18</td><td>5</td><td>1</td><td>12</td><td>60:95</td><td>16</td><td>-35</td></tr>"
        "<tr><td>11.</td><td><img alt='logo'></td><td>HC Roudnice</td><td>18</td><td>4</td><td>2</td><td>12</td><td>50:80</td><td>14</td><td>-30</td></tr>"
        "</table></body></html>"
    )
    conn = GenericHtmlTableConnector()
    data = conn.parse(parse_doc(decode_html(no_hdr.encode('cp1250'), 'charset=windows-1250')), URL)
    row = next(s for s in data.standings if s.team_name == 'HC Smíchov 1913')
    assert (row.played, row.wins, row.draws, row.losses) == (18, 6, 3, 9)
    assert row.score == '86:78' and row.points == 22 and row.plus_minus == -5
