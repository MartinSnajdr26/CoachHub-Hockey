# -*- coding: utf-8 -*-
"""View-model tests for the league service (no network): verifies the dashboard
view built from cached data — Naše pozice values, form codes (no Draw), and that
cache written by an older parser (no/old _schema) is never shown as real data."""
import json
import pytest

from coach.app import app
from coach.extensions import db
from coach.models import Team, LeagueIntegration
from coach.services.league import service as svc
from coach.services.league import get_connector
from coach.services.league.base import decode_html, parse_doc
from coach.tests.test_league_parser import SAMPLE, URL


@pytest.fixture
def ctx():
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    with app.app_context():
        db.drop_all()
        db.create_all()
        t = Team(name='HC Smíchov 1913')
        db.session.add(t)
        db.session.commit()
        yield t.id
        db.session.remove()
        db.drop_all()


def _seed(team_id, with_schema=True, form=None):
    svc.save_config(team_id, True, URL, 'HC Smíchov 1913')
    li = svc.get_integration(team_id)
    conn = get_connector(URL)
    data = conn.parse(parse_doc(decode_html(SAMPLE.encode('cp1250'), 'charset=windows-1250')), URL).to_dict()
    if form is not None:
        data['team_form'] = form
        data['form_partial'] = len(form) < svc.FORM_NEED
    if with_schema:
        data['_schema'] = svc.CACHE_SCHEMA
    li.data_json = json.dumps(data, ensure_ascii=False)
    db.session.commit()
    return li


def test_view_nase_pozice(ctx):
    _seed(ctx, form=['L', 'L', 'OW'])
    v = svc.get_view(ctx)
    assert v['stale_schema'] is False
    tr = v['team_row']
    assert tr is not None
    assert tr['team_name'] == 'HC Smíchov 1913'
    assert tr['position'] == 9
    assert tr['played'] == 18
    assert tr['points'] == 22
    assert tr['score'] == '86:78'
    assert (tr['wins'], tr['draws'], tr['losses']) == (6, 3, 9)
    assert tr['plus_minus'] == -5


def test_view_form_no_draw(ctx):
    _seed(ctx, form=['L', 'L', 'OW', 'OL'])
    v = svc.get_view(ctx)
    assert 'D' not in v['form']
    assert set(v['form']) <= {'W', 'L', 'OW', 'OL'}
    assert v['form'] == ['L', 'L', 'OW', 'OL']


def test_old_schema_cache_not_displayed(ctx):
    """Cache written by the old parser (no _schema) must be flagged stale, NOT
    shown with wrong numbers like 1913 played / 8678 points."""
    li = _seed(ctx, with_schema=False)
    # simulate corrupt old data too
    bad = json.loads(li.data_json)
    bad.pop('_schema', None)
    bad['standings'][1]['played'] = 1913
    bad['standings'][1]['points'] = 8678
    li.data_json = json.dumps(bad, ensure_ascii=False)
    db.session.commit()
    v = svc.get_view(ctx)
    assert v['stale_schema'] is True
    assert v['standings'] == []
    assert v['team_row'] is None


def test_sanity_guard_rejects_corrupt_points(ctx):
    li = _seed(ctx, with_schema=True)
    bad = json.loads(li.data_json)
    bad['standings'][1]['points'] = 8678  # stripped score leaked into points
    li.data_json = json.dumps(bad, ensure_ascii=False)
    db.session.commit()
    v = svc.get_view(ctx)
    assert v['stale_schema'] is True
