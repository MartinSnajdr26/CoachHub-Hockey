"""vysledky.com connector (classic server-rendered `soutez2.php` pages).

Reuses the generic table heuristics for standings/results and adds
vysledky-specific competition metadata (name, region, season) from the page
title and headings. Robust to Windows-1250 and to logo images in cells.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import asdict

from .generic_html import GenericHtmlTableConnector
from .base import fetch_html, parse_doc


class VysledkyConnector(GenericHtmlTableConnector):
    name = "vysledky"

    def matches(self, url):
        return 'vysledky.com' in (url or '').lower()

    # ---- round navigation (used only during refresh, never on dashboard) ----
    def _id_soutez(self, url):
        try:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            return (q.get('id_soutez') or [''])[0]
        except Exception:
            return ''

    # current round label / nav button: "22.kolo", "21. kolo", title='21.kolo'
    _ROUND_NAV_RE = re.compile(r'(\d{1,3})\s*\.\s*kolo', re.I)

    def detect_round(self, results, html=None):
        """Current round number for the competition.

        Preferred source is the page's round-navigation label (e.g. "22.kolo"
        next to the < / > buttons), which lives in a <div> and never reaches the
        table parser — so it is read from the raw `html` when provided. Falls
        back to the highest 'N. kolo' marker carried by the parsed results.
        Returns the round int or None."""
        mx = 0
        if html:
            for m in self._ROUND_NAV_RE.finditer(html):
                mx = max(mx, int(m.group(1)))
        if not mx:
            for r in results:
                rnd = (r.get('round') if isinstance(r, dict) else getattr(r, 'round', '')) or ''
                m = re.search(r'(\d{1,3})', rnd)
                if m:
                    mx = max(mx, int(m.group(1)))
        return mx or None

    def fetch_round(self, url, kolo):
        """Fetch a single previous round via the public AJAX endpoint and return
        its results (list of dicts). Best-effort; returns [] on any problem."""
        sid = self._id_soutez(url)
        if not sid:
            return []
        p = urllib.parse.urlparse(url)
        ajax = '%s://%s/ajax-soutez2.php?akce=1&sport=2&id_soutez=%s&kolo=%s' % (
            p.scheme, p.netloc, sid, kolo)
        try:
            doc = parse_doc(fetch_html(ajax))
            return [asdict(r) for r in self._results(doc, skip_idx=None)]
        except Exception:
            return []

    def parse(self, doc, url):
        data = super().parse(doc, url)
        title = (doc.title or '').strip()

        # competition name: first heading, else title up to a separator
        if doc.headings:
            data.info.competition_name = doc.headings[0][:200]
        elif title:
            data.info.competition_name = re.split(r'[|–—\-]', title)[0].strip()[:200]

        # season: 2024/2025, 2024-2025 or 2024
        for txt in [title] + doc.headings:
            m = re.search(r'(20\d{2}\s*/\s*20\d{2}|20\d{2}\s*-\s*20\d{2}|20\d{2})', txt or '')
            if m:
                data.info.season = m.group(1).replace(' ', '')
                break

        # region / league line — prefer a secondary heading (e.g. "Ústecký kraj")
        for h in doc.headings[1:]:
            if re.search(r'(kraj|liga|přebor|prebor|divize|soutěž|soutez|třída|trida|oblast)', h, re.I):
                data.info.region = h[:120]
                break

        return data
