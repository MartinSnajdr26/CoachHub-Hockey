"""Base connector: normalized data structures, polite fetch, stdlib HTML extraction.

No third-party dependencies (urllib + html.parser only), matching the existing
Týmuj ICS connector style. Designed so the delivery/parse layers can evolve
without changing the data contract consumed by the UI.
"""
from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from coach.services.url_safety import validate_public_http_url, safe_urlopen

USER_AGENT = "CoachHubHockey/1.0 (+https://coachhubhockey.com; league widget)"
MAX_BYTES = 3 * 1024 * 1024          # cap download size (do not overload / OOM)
TIMEOUT = 10                          # seconds

SCORE_RE = re.compile(r'^(\d{1,3})\s*[:\-]\s*(\d{1,3})$')
INT_RE = re.compile(r'^-?\d{1,4}$')


# ----------------------------- normalized data -----------------------------
@dataclass
class StandingRow:
    position: int = 0
    team_name: str = ""
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    score: str = ""          # kept verbatim, e.g. "86:78" (never colon-stripped)
    points: int = 0
    plus_minus: int = 0


@dataclass
class MatchResult:
    date: str = ""
    home_team: str = ""
    away_team: str = ""
    home_score: "int | None" = None
    away_score: "int | None" = None
    status: str = ""        # 'finished' | 'scheduled'
    round: str = ""
    ot: bool = False        # decided in overtime / shootout (pp / sn)


@dataclass
class CompetitionInfo:
    competition_name: str = ""
    region: str = ""
    season: str = ""
    source_url: str = ""
    last_updated: str = ""


@dataclass
class CompetitionData:
    info: CompetitionInfo = field(default_factory=CompetitionInfo)
    standings: list = field(default_factory=list)   # list[StandingRow]
    results: list = field(default_factory=list)      # list[MatchResult]

    def to_dict(self):
        return {
            "info": asdict(self.info),
            "standings": [asdict(s) for s in self.standings],
            "results": [asdict(r) for r in self.results],
        }


# ----------------------------- fetch + decode -----------------------------
def _detect_encoding(raw, ctype=""):
    enc = None
    m = re.search(r'charset=["\']?([\w-]+)', ctype or '', re.I)
    if m:
        enc = m.group(1)
    if not enc:
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:2048], re.I)
        if m:
            try:
                enc = m.group(1).decode('ascii', 'ignore')
            except Exception:
                enc = None
    return enc


def fetch_html_with_meta(url):
    """GET a page with polite headers, size + time limits. Returns decoded text.

    Only http(s); no cookies/auth (never bypasses logins). Raises on failure.
    """
    ok, msg = validate_public_http_url(url)
    if not ok:
        raise ValueError(msg)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "cs,en;q=0.8",
    }
    # safe_urlopen re-validates every redirect hop (SSRF protection).
    with safe_urlopen(url, timeout=TIMEOUT, headers=headers, max_redirects=3) as resp:
        raw = resp.read(MAX_BYTES + 1)[:MAX_BYTES]
        ctype = resp.headers.get('Content-Type', '')
        status = getattr(resp, 'status', None) or getattr(resp, 'code', None)
    encoding = _detect_encoding(raw, ctype)
    return decode_html(raw, ctype), {
        'url': url,
        'http_status': status,
        'bytes': len(raw),
        'content_type': ctype,
        'encoding': encoding or 'auto',
    }


def fetch_html(url):
    html, _meta = fetch_html_with_meta(url)
    return html


def decode_html(raw, ctype=""):
    """Decode bytes handling Czech encodings (Windows-1250 / ISO-8859-2 / UTF-8)."""
    enc = _detect_encoding(raw, ctype)
    for cand in [enc, 'utf-8', 'cp1250', 'iso-8859-2']:
        if not cand:
            continue
        try:
            return raw.decode(cand)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode('utf-8', errors='replace')


# ----------------------------- HTML extraction -----------------------------
class HtmlDoc(HTMLParser):
    """Extract every table (including nested layout tables) as rows of cell text,
    plus <title> and headings. Skips script/style/form/select/iframe so ads,
    login forms and JS are ignored. Image alt/title is used as cell text so a
    team logo cell still yields the team name when present."""

    _SKIP = ('script', 'style', 'form', 'select', 'noscript', 'iframe', 'svg', 'button')

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []          # list[list[list[str]]]
        self.title = ""
        self.headings = []        # list[str]
        self._skip = 0
        self._stack = []          # nested tables: [{'rows':[], 'row':None, 'cell':None}]
        self._in_title = False
        self._in_head = None
        self._head_buf = []

    def _implicit_close_cell(self, top):
        """Close a cell that has no explicit </td> (it is implicitly closed by the
        next td/th/tr). vysledky.com result rows omit the </td> after the home
        team, e.g. ``<td>...<b>Žebrák</b><td>...<b>4:3</b></td>``. Keep the text
        only when non-empty so real data (the home-team name) survives, while the
        empty 1px separator cells of standings rows stay dropped — leaving
        well-formed standings rows byte-for-byte identical to before."""
        if top['cell'] is not None:
            text = ' '.join(' '.join(top['cell']).split())
            if text and top['row'] is not None:
                top['row'].append(text)
            top['cell'] = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self._SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == 'title':
            self._in_title = True
            return
        if tag in ('h1', 'h2', 'h3'):
            self._in_head = tag
            self._head_buf = []
            return
        if tag == 'table':
            self._stack.append({'rows': [], 'row': None, 'cell': None})
            return
        if not self._stack:
            return
        top = self._stack[-1]
        if tag == 'tr':
            self._implicit_close_cell(top)
            top['row'] = []
        elif tag in ('td', 'th'):
            self._implicit_close_cell(top)
            if top['row'] is None:
                top['row'] = []
            top['cell'] = []
        elif tag == 'img' and top['cell'] is not None:
            alt = (a.get('alt') or a.get('title') or '').strip()
            if alt and alt.lower() not in ('logo', 'znak', 'erb'):
                top['cell'].append(alt)
        elif tag == 'br' and top['cell'] is not None:
            top['cell'].append(' ')

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            if self._skip:
                self._skip -= 1
            return
        if self._skip:
            return
        if tag == 'title':
            self._in_title = False
            return
        if tag in ('h1', 'h2', 'h3') and self._in_head == tag:
            txt = ' '.join(' '.join(self._head_buf).split())
            if txt:
                self.headings.append(txt)
            self._in_head = None
            self._head_buf = []
            return
        if not self._stack:
            return
        top = self._stack[-1]
        if tag in ('td', 'th') and top['cell'] is not None:
            top['row'].append(' '.join(' '.join(top['cell']).split()))
            top['cell'] = None
        elif tag == 'tr':
            self._implicit_close_cell(top)
            if top['row'] is not None:
                top['rows'].append(top['row'])
                top['row'] = None
        elif tag == 'table':
            t = self._stack.pop()
            if t['rows']:
                self.tables.append(t['rows'])

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        if self._in_head is not None:
            self._head_buf.append(data)
            return
        if self._stack and self._stack[-1]['cell'] is not None:
            t = data.strip()
            if t:
                self._stack[-1]['cell'].append(t)


def parse_doc(html):
    d = HtmlDoc()
    try:
        d.feed(html)
    except Exception:
        pass
    return d


def as_int(s, default=0):
    try:
        return int(re.sub(r'[^\d-]', '', str(s)))
    except Exception:
        return default


# ----------------------------- base connector -----------------------------
class BaseLeagueConnector:
    name = "base"

    def matches(self, url):
        return False

    def parse(self, doc, url):
        raise NotImplementedError

    def fetch_and_parse(self, url):
        html = fetch_html(url)
        doc = parse_doc(html)
        data = self.parse(doc, url)
        data.info.source_url = url
        data.info.last_updated = datetime.now(timezone.utc).isoformat()
        return data
