"""Generic HTML-table league connector.

Parsing is CELL-STRUCTURE based (not "extract every number from the row text"),
which is what makes team names containing digits (e.g. "HC Smíchov 1913") safe:

  * Standings — the table with the most standings-shaped rows. Columns are taken
    from the header row when present (Z/V/R/P/Skóre/B/+−), otherwise ANCHORED on
    the skóre cell: the 4 integer cells immediately before it are Z,V,R,P; the
    cells after are B and +/-. The team cell is read as TEXT ONLY (its digits are
    never treated as stats). Score is kept verbatim ("86:78"); goals_for/against
    are derived by splitting on ':'. Points come strictly from the B column.
  * Results — rows (outside the standings table) with a small score cell that has
    a real team cell on BOTH sides (so times/dates are never mistaken for scores,
    and the away team is never dropped). Logo/image cells are empty -> ignored.
"""
from __future__ import annotations

import re

from .base import (
    BaseLeagueConnector, CompetitionData, CompetitionInfo,
    StandingRow, MatchResult, SCORE_RE, INT_RE, as_int,
)

# header label -> normalized field (matched case-insensitively, trailing '.' stripped)
_HEADERS = {
    'played': ('z', 'záp', 'zápasy', 'zapasy', 'utk', 'utkání', 'utkani'),
    'wins':   ('v', 'výhry', 'vyhry'),
    'draws':  ('r', 'remízy', 'remizy'),
    'losses': ('p', 'prohry'),
    'points': ('b', 'body', 'bodů', 'bodu', 'bd'),
    'score':  ('skóre', 'skore', 'góly', 'goly', 'branky'),
    'team':   ('tým', 'tym', 'mužstvo', 'muzstvo', 'klub', 'družstvo', 'druzstvo', 'team', 'oddíl', 'oddil'),
    'pos':    ('#', 'poř', 'por', 'pořadí', 'poradi', 'rk', 'č', 'c'),
    'plus_minus': ('+/-', '+/−', '+/–', '+-', 'rozdíl', 'rozdil', 'rozd'),
}

# A *results* score: 1–2 digits each, both <= 30 (hockey scores; rejects times like 17:45).
# Optional trailing pp/sn marks an overtime/shootout decision ("4:3pp", "2:1 sn").
RESULT_SCORE_RE = re.compile(r'^(\d{1,2})\s*[:\-]\s*(\d{1,2})\s*(pp|sn|p\.p\.|sn\.)?\.?$', re.I)
DATE_RE = re.compile(r'\d{1,2}\.\s*\d{1,2}\.')          # 7.2. / 07.02.2026
TIME_RE = re.compile(r'^\d{1,2}:\d{2}$')                # standalone 17:45
ROUND_RE = re.compile(r'(\d{1,2})\.\s*kolo')
# overtime / shootout markers shown by vysledky (prodloužení / samostatné nájezdy)
OT_RE = re.compile(r'(\bpp\b|\bsn\b|p\.\s*p\.|sn\.|prodlou|nájezd|najezd|po\s*nájezd)', re.I)


def _is_team_cell(c):
    """Text cell usable as a team name (digits allowed inside it), but not an
    integer, score, date, time or round marker, and not empty/logo."""
    c = (c or '').strip()
    if not c or INT_RE.match(c) or RESULT_SCORE_RE.match(c) or TIME_RE.match(c):
        return False
    if DATE_RE.search(c):
        return False
    if ROUND_RE.match(c.lower()):
        return False
    return True


class GenericHtmlTableConnector(BaseLeagueConnector):
    name = "generic"

    def matches(self, url):
        return False  # generic is the registry fallback, never claims a URL

    # -- public API --
    def parse(self, doc, url):
        standings, stand_idx = self._standings(doc)
        results = self._results(doc, skip_idx=stand_idx)
        info = CompetitionInfo(competition_name=self._competition_name(doc))
        return CompetitionData(info=info, standings=standings, results=results)

    def _competition_name(self, doc):
        if doc.headings:
            return doc.headings[0][:200]
        return (doc.title or "").strip()[:200]

    # ---------------- standings ----------------
    def _standings(self, doc):
        best, best_n, best_idx = [], 0, None
        for idx, tbl in enumerate(doc.tables):
            rows = [r for r in tbl if any(c.strip() for c in r)]
            if len(rows) < 3:
                continue
            parsed = self._try_standings(rows)
            if parsed and len(parsed) > best_n:
                best, best_n, best_idx = parsed, len(parsed), idx
        return best, best_idx

    def _map_header(self, rows):
        for idx in range(min(3, len(rows))):
            cells = [c.strip().lower().rstrip('.') for c in rows[idx]]
            cols = {}
            for ci, c in enumerate(cells):
                for fld, toks in _HEADERS.items():
                    if fld in cols:
                        continue
                    if c in toks:
                        cols[fld] = ci
            if len(cols) >= 4 or ('score' in cols and 'points' in cols):
                return idx, cols
        return None, {}

    def _try_standings(self, rows):
        hdr_idx, cols = self._map_header(rows)
        data_rows = rows[hdr_idx + 1:] if hdr_idx is not None else rows
        out = []
        for r in data_rows:
            row = self._standing_row(r, cols)
            if row:
                out.append(row)
        if len(out) >= 2:
            for i, s in enumerate(out):
                if not s.position:
                    s.position = i + 1
            return out
        return None

    def _standing_row(self, r, cols):
        cells = [c.strip() for c in r]
        if not any(cells):
            return None
        # anchor: the skóre cell (1–3 digits each), kept verbatim
        score_i, gf, ga, score_str = -1, 0, 0, ""
        for i, c in enumerate(cells):
            m = SCORE_RE.match(c)
            if m:
                score_i, gf, ga, score_str = i, int(m.group(1)), int(m.group(2)), c
                break
        if score_i < 0:
            return None  # hockey standings rows always carry a skóre cell
        row = StandingRow(goals_for=gf, goals_against=ga, score=score_str, plus_minus=gf - ga)

        if cols:
            # read ONLY explicitly mapped columns (team cell stays text)
            offset = 0
            mapped_score_i = cols.get('score')
            if mapped_score_i is not None and mapped_score_i != score_i:
                # Some vysledky.com standings headers omit logo/team placeholder
                # columns while data rows include them. Align mapped stat columns
                # to the actual score cell detected in the data row.
                offset = score_i - mapped_score_i

            def col(field, aligned=True):
                ci = cols.get(field)
                if ci is None:
                    return None
                if aligned:
                    ci = ci + offset
                return cells[ci] if 0 <= ci < len(cells) else None
            team = col('team', aligned=False)
            if not _is_team_cell(team):
                shifted_team = col('team', aligned=True)
                if _is_team_cell(shifted_team):
                    team = shifted_team
            row.team_name = (team or self._fallback_team(cells, score_i))[:120]
            for field, attr in (('played', 'played'), ('wins', 'wins'),
                                ('draws', 'draws'), ('losses', 'losses'),
                                ('points', 'points'), ('pos', 'position')):
                v = col(field, aligned=(field != 'pos'))
                if v is not None:
                    setattr(row, attr, as_int(v))
            if 'plus_minus' in cols:
                v = col('plus_minus')
                if v is not None and re.search(r'\d', v):
                    row.plus_minus = as_int(v)
            # safety: if B column wasn't mapped, points = the integer right after skóre
            if 'points' not in cols and score_i + 1 < len(cells):
                row.points = as_int(cells[score_i + 1])
            return row

        # ----- no header: anchor on skóre -----
        # contiguous integer cells immediately before skóre = Z, V, R, P (closest 4)
        stats = []
        j = score_i - 1
        while j >= 0 and INT_RE.match(cells[j]):
            stats.insert(0, as_int(cells[j]))
            j -= 1
        # A standings row needs several integer stat columns before the skóre.
        # This rejects results rows ("date, Home, 4:3, Away") which have none.
        if len(stats) < 3:
            return None
        s4 = stats[:4] if len(stats) > 4 else stats[-4:]
        if len(s4) >= 1:
            row.played = s4[0]
        if len(s4) >= 2:
            row.wins = s4[1]
        if len(s4) >= 3:
            row.draws = s4[2]
        if len(s4) >= 4:
            row.losses = s4[3]
        # team = nearest text cell before the stat block (digits inside are fine)
        row.team_name = self._fallback_team(cells, score_i, before=j)[:120]
        # position = leading "9." style cell
        if cells and cells[0].rstrip('.').isdigit() and len(cells[0]) <= 4:
            row.position = as_int(cells[0])
        # after skóre: first int = points (B), second int = plus_minus
        after_ints = [c for c in cells[score_i + 1:] if re.match(r'^[+-]?\d+$', c)]
        if after_ints:
            row.points = as_int(after_ints[0])
        if len(after_ints) >= 2:
            row.plus_minus = as_int(after_ints[1])
        return row

    @staticmethod
    def _fallback_team(cells, score_i, before=None):
        rng = range((before if before is not None else score_i - 1), -1, -1)
        for k in rng:
            if _is_team_cell(cells[k]):
                return cells[k]
        # last resort: longest team-ish cell anywhere
        cand = [c for i, c in enumerate(cells) if i != score_i and _is_team_cell(c)]
        return max(cand, key=len) if cand else ''

    # ---------------- results ----------------
    def _results(self, doc, skip_idx=None):
        out = []
        rnd = ""
        for idx, tbl in enumerate(doc.tables):
            if idx == skip_idx:
                continue
            for r in tbl:
                cells = [c.strip() for c in r]
                non_empty = [c for c in cells if c]
                mk = ROUND_RE.search(' '.join(non_empty).lower())
                if mk and len(non_empty) <= 3:
                    rnd = mk.group(0)
                for si, c in enumerate(cells):
                    m = RESULT_SCORE_RE.match(c)
                    if not m or int(m.group(1)) > 30 or int(m.group(2)) > 30:
                        continue
                    before = [cells[j] for j in range(si - 1, -1, -1) if _is_team_cell(cells[j])]
                    after = [cells[j] for j in range(si + 1, len(cells)) if _is_team_cell(cells[j])]
                    home = before[0] if before else ''
                    away = after[0] if after else ''
                    if home and not away and len(before) >= 2:
                        # Common layout: date, home, away, score.
                        away = before[0]
                        home = before[1]
                    elif away and not home and len(after) >= 2:
                        # Less common layout: score, home, away.
                        home = after[0]
                        away = after[1]
                    if not (home and away):
                        continue  # not a real result (e.g. a time, or missing side)
                    date = next((cells[j] for j in range(len(cells))
                                 if DATE_RE.search(cells[j])), '')
                    ot = bool(m.group(3)) or bool(OT_RE.search(' '.join(x for x in non_empty if x != c)))
                    out.append(MatchResult(date=date, home_team=home[:120], away_team=away[:120],
                                           home_score=int(m.group(1)), away_score=int(m.group(2)),
                                           status='finished', round=rnd, ot=ot))
                    break  # one result per row
        seen, uniq = set(), []
        for r in out:
            k = (r.home_team, r.away_team, r.home_score, r.away_score, r.date, r.round)
            if k in seen:
                continue
            seen.add(k)
            uniq.append(r)
        return uniq[:30]
