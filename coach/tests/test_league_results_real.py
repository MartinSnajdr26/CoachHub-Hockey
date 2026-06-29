# -*- coding: utf-8 -*-
"""Regression tests for the League results parser against the REAL downloaded
vysledky.com HTML (id_soutez=19284), captured under tests/fixtures/.

The real page differs from a hand-written sample in one decisive way: result
rows omit the </td> after the home team, e.g.

    <td width=151><b>Žebrák</b><td width=50><b>4:3</b></td>

The stdlib HTML extractor used to drop that unclosed cell, so the home team
vanished and every result row failed the "team on both sides of the score"
check -> 0 results parsed. These tests lock in the fix and the previous-round /
form behaviour."""
import os
from dataclasses import asdict

from coach.services.league.base import decode_html, parse_doc
from coach.services.league import get_connector
from coach.services.league import service as svc

URL = "https://vysledky.com/soutez2.php?id_soutez=19284"
FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    raw = open(os.path.join(FIX, name), "rb").read()
    return decode_html(raw, "text/html; charset=windows-1250")


def _parse_main():
    html = _load("vysledky_soutez_19284.html")
    conn = get_connector(URL)
    return conn, html, conn.parse(parse_doc(html), URL)


# ----------------------------- current results -----------------------------
def test_current_results_parse_more_than_zero():
    _, _, data = _parse_main()
    assert len(data.results) > 0


def test_first_match_includes_both_teams():
    _, _, data = _parse_main()
    first = data.results[0]
    assert first.home_team == "Žebrák"          # recovered despite missing </td>
    assert first.away_team == "Smíchov"          # away never dropped
    assert first.date.startswith("So 07.02. 2026")


def test_score_4_3_parsed_as_score_not_time():
    _, _, data = _parse_main()
    first = data.results[0]
    assert first.home_score == 4 and first.away_score == 3


def test_time_1745_not_treated_as_score():
    """The 17:45 kick-off time shares the row with the 4:3 score; it must never
    become the result."""
    _, _, data = _parse_main()
    for r in data.results:
        assert (r.home_score, r.away_score) != (17, 45)
        # every parsed score is a plausible hockey score, not a clock value
        assert r.away_score < 60


def test_czech_characters_preserved():
    _, _, data = _parse_main()
    names = {r.home_team for r in data.results} | {r.away_team for r in data.results}
    assert any("Č" in n or "í" in n or "ž" in n.lower() for n in names)


# ----------------------------- standings unchanged --------------------------
def test_standings_still_ten_rows():
    _, _, data = _parse_main()
    assert len(data.standings) == 10


def test_standings_rows_not_parsed_as_results():
    """No standings team (with its big season totals) leaks into results, and no
    'result' carries an impossible standings-sized score."""
    _, _, data = _parse_main()
    for r in data.results:
        assert r.home_score is not None and 0 <= r.home_score <= 40
        assert r.away_score is not None and 0 <= r.away_score <= 40


def test_standings_values_intact():
    _, _, data = _parse_main()
    row = next(s for s in data.standings if s.team_name == "HC Smíchov 1913")
    assert row.position == 9
    assert (row.played, row.wins, row.draws, row.losses) == (18, 6, 3, 9)
    assert row.score == "86:78" and row.points == 22 and row.plus_minus == -5


# ----------------------------- previous rounds / form -----------------------
def test_detect_round_from_nav():
    conn, html, _ = _parse_main()
    assert conn.detect_round([], html=html) == 22


def test_previous_round_fragment_parses():
    html = _load("vysledky_round21_kolo21.html")
    conn = get_connector(URL)
    res = conn._results(parse_doc(html), skip_idx=None)
    assert len(res) > 0
    smichov = next(r for r in res if "Smíchov" in (r.home_team + r.away_team))
    assert smichov.home_team == "Smíchov" and smichov.away_team == "Kutná Hora B"
    assert smichov.home_score == 10 and smichov.away_score == 1


def test_form_collected_from_main_plus_previous_rounds(monkeypatch):
    """End-to-end form: round 22 from the main page + walking previous rounds.
    The network is stubbed with the captured round-21 fragment so the test is
    offline and deterministic."""
    conn, html, data = _parse_main()
    results = [asdict(r) for r in data.results]
    frag = _load("vysledky_round21_kolo21.html")
    frag_results = [asdict(r) for r in conn._results(parse_doc(frag), skip_idx=None)]

    # any previous round returns the captured fragment (Smíchov won 10:1 there)
    monkeypatch.setattr(conn, "fetch_round", lambda url, kolo: frag_results)
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)

    form, partial = svc._collect_form(conn, URL, "HC Smichov 1913", results, html=html)
    assert len(form) == 5            # main page (1 game) + previous rounds
    assert all(c in ("W", "L", "OW", "OL") for c in form)
    assert "D" not in form           # hockey form never records a draw
    assert form[0] == "L"            # round 22: Žebrák 4:3 Smíchov (away loss)
    assert form[1] == "W"            # round 21: Smíchov 10:1 Kutná Hora B
    assert partial is False
