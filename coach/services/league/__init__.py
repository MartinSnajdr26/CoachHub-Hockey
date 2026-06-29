"""League results & standings integration.

Architecture (pluggable connectors):
    BaseLeagueConnector          - interface + safe fetch + normalization
    GenericHtmlTableConnector    - heuristic HTML-table parser (any site)
    VysledkyConnector            - vysledky.com specifics (extends generic)

All connectors return NORMALIZED data (CompetitionData) so widgets and
caching never depend on a specific site's markup. Add a new site by writing
a connector and registering it below.
"""
from .base import (
    StandingRow, MatchResult, CompetitionInfo, CompetitionData,
    BaseLeagueConnector,
)
from .generic_html import GenericHtmlTableConnector
from .vysledky import VysledkyConnector

# Order matters: most specific first, generic fallback last.
_REGISTRY = [VysledkyConnector(), GenericHtmlTableConnector()]


def get_connector(url):
    """Pick the connector whose matches(url) is True; fall back to generic."""
    for c in _REGISTRY:
        try:
            if c.matches(url):
                return c
        except Exception:
            continue
    return GenericHtmlTableConnector()


__all__ = [
    'StandingRow', 'MatchResult', 'CompetitionInfo', 'CompetitionData',
    'BaseLeagueConnector', 'GenericHtmlTableConnector', 'VysledkyConnector',
    'get_connector',
]
