# -*- coding: utf-8 -*-
"""Drill export selection (/drills/select) — desktop presentation regressions.

Two defects are pinned down here:

1. The `← Zpět na kategorie` / `➕ Nové cvičení` links were invisible. Root cause:
   `.link-contrast` used `var(--on-primary)` (#08101a) — the foreground meant to
   sit ON the gold primary fill — on the dark PAGE background, with `!important`
   blocking any override.

2. The drill title was covered by the selection controls, because
   `.card .selection-toolbar` was `position: absolute; top/right: 10px` and the
   `<h2>` flowed underneath it.

Plus the constraint that makes this risky: mobile.css reflows this page with
STRUCTURAL selectors (`#exportForm > div:first-of-type`, `> .cards + div`,
`.card > p`, `form[method="get"] > input[name=q]`), and in places supplies only
part of a rule because the template used to carry inline styles. Those tests
exist so a future cleanup cannot quietly break the mobile layout.
"""
import os
import re
import unittest

from coach.app import app
from coach.extensions import db
from coach.models import Drill, Team, TeamKey
from coach.services.keys import hash_team_key

STYLE_CSS = os.path.join(app.static_folder, 'style.css')
PAGE_CSS = os.path.join(app.static_folder, 'drills_select.css')
MOBILE_CSS = os.path.join(app.static_folder, 'mobile.css')
SCOPE = 'body[data-page="drills_select"]'


def _css(path):
    return re.sub(r'/\*.*?\*/', '', open(path, encoding='utf-8').read(), flags=re.S)


def _rules(css):
    return re.findall(r'([^{}]+)\{([^{}]*)\}', css)


class LinkContrastRootCauseTest(unittest.TestCase):
    """Defect 1 — fixed at the source, not overridden."""

    def setUp(self):
        self.css = _css(STYLE_CSS)

    def _link_contrast_decls(self):
        out = []
        for sel, decls in _rules(self.css):
            if re.search(r'\.link-contrast(?![\w-])', sel):
                out.append((sel.strip(), decls))
        return out

    def test_rule_exists(self):
        self.assertTrue(self._link_contrast_decls())

    def test_never_paints_itself_with_the_on_primary_foreground(self):
        for sel, decls in self._link_contrast_decls():
            m = re.search(r'(?<!-)color\s*:\s*([^;]+)', decls)
            if m:
                self.assertNotIn('--on-primary', m.group(1),
                                 'dark-on-dark again in: %s' % sel)

    def test_base_rule_uses_the_normal_foreground(self):
        base = [d for s, d in self._link_contrast_decls()
                if ':hover' not in s and ':focus' not in s]
        self.assertTrue(base)
        self.assertTrue(any('var(--text)' in d for d in base))

    def test_no_important_blocking_later_overrides(self):
        for sel, decls in self._link_contrast_decls():
            self.assertNotIn('!important', decls, sel)

    def test_has_a_hover_and_focus_state(self):
        sels = ' '.join(s for s, _ in self._link_contrast_decls())
        self.assertIn(':hover', sels)
        self.assertIn(':focus', sels)


class PageCssIsTightlyScopedTest(unittest.TestCase):
    """Requirement: no generic .card / a / button / input rule may be touched."""

    def test_every_selector_is_page_scoped(self):
        unscoped = []
        for sel, _ in _rules(_css(PAGE_CSS)):
            for part in sel.split(','):
                part = part.strip()
                if not part or part.startswith('@'):
                    continue
                if SCOPE not in part:
                    unscoped.append(part)
        self.assertEqual(unscoped, [], 'unscoped selector(s): %s' % unscoped)

    def test_toolbar_is_taken_out_of_the_overlay_on_desktop(self):
        css = _css(PAGE_CSS)
        m = re.search(r'\.ds-card \.selection-toolbar\s*\{([^}]*)\}', css)
        self.assertIsNotNone(m, 'no rule neutralising the absolute toolbar')
        self.assertRegex(m.group(1), r'position\s*:\s*static')

    def test_fix_is_not_a_blunt_top_padding(self):
        """The card must not simply be padded to clear an overlay."""
        css = _css(PAGE_CSS)
        for sel, decls in _rules(css):
            if '.ds-card' in sel and 'head' not in sel:
                self.assertNotRegex(decls, r'padding-top\s*:\s*[3-9]\d')

    def test_no_one_off_hex_colors(self):
        """Theme tokens only (a bare #rgb/#rrggbb would be a one-off)."""
        self.assertEqual(re.findall(r'#[0-9a-fA-F]{3,8}\b', _css(PAGE_CSS)), [])


class DrillsSelectRenderTest(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        team = Team(name='HC Test')
        db.session.add(team)
        db.session.flush()
        self.tid = team.id
        db.session.add(TeamKey(team_id=self.tid, role='coach', key_hash=hash_team_key('ck')))
        self.drill = Drill(team_id=self.tid, category='Útok', duration=20,
                           name='Nácvik přesilové hry 5 na 4 — rozestavení a rotace')
        db.session.add(self.drill)
        db.session.commit()
        self.did = self.drill.id
        self.client = app.test_client()
        with self.client.session_transaction() as s:
            s['team_id'] = self.tid
            s['team_role'] = 'coach'
            s['team_login'] = True
            s['auth_method'] = 'team_key'

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def html(self):
        resp = self.client.get('/drills/select')
        self.assertEqual(resp.status_code, 200)
        return resp.get_data(as_text=True)

    # -- wiring -------------------------------------------------------
    def test_page_loads_its_scoped_stylesheet(self):
        self.assertIn('drills_select.css', self.html())

    def test_body_carries_the_scope_hook(self):
        self.assertIn('data-page="drills_select"', self.html())

    def test_nav_links_keep_the_link_contrast_class(self):
        """mobile.css hides them via `a.link-contrast`; renaming would make them
        reappear on phones."""
        html = self.html()
        self.assertRegex(html, r'class="link-contrast[^"]*"[^>]*>\s*←')
        self.assertIn('link-contrast', html)
        self.assertEqual(html.count('link-contrast'), 2)

    # -- defect 2: card header ---------------------------------------
    def test_card_uses_a_header_instead_of_an_overlay(self):
        html = self.html()
        head = re.search(r'<div class="ds-card-head">(.*?)</div>\s*\n\s*(?:\{#.*?#\}\s*)?<p',
                         html, re.S)
        self.assertIsNotNone(head, 'no .ds-card-head wrapper')
        self.assertIn('selection-toolbar', head.group(1))
        self.assertIn('ds-card-title', head.group(1))

    def test_title_is_present_and_intact(self):
        self.assertIn(self.drill.name, self.html())

    def test_card_is_no_longer_a_positioning_context(self):
        """The inline `position:relative` existed only for the absolute overlay."""
        html = self.html()
        card = html[html.find('ds-card'):html.find('ds-card') + 200]
        self.assertNotIn('position:relative', card.replace(' ', ''))

    # -- inline-style cleanup ----------------------------------------
    def test_page_no_longer_ships_one_off_inline_colors(self):
        html = self.html()
        body = html[html.find('Vybrat tréninky'):]
        for junk in ('#ccc', '#888', 'opacity:0.8'):
            self.assertNotIn(junk, body)

    # -- mobile structural contract ----------------------------------
    def test_export_name_row_is_still_the_first_div_of_the_form(self):
        """mobile.css targets `#exportForm > div:first-of-type`."""
        html = self.html()
        form = html[html.find('id="exportForm"'):]
        first_div = form[form.find('<div'):]
        self.assertIn('session_title', first_div[:400])

    def test_bottom_actions_still_follow_the_cards_grid(self):
        """mobile.css pins `#exportForm > .cards + div` as the sticky bar."""
        html = self.html()
        after = html[html.find('</div>', html.find('class="cards"')):]
        self.assertRegex(after, r'</div>\s*(?:\{#.*?#\}\s*)?<div class="ds-actions ds-actions--bottom"',)

    def test_meta_paragraph_is_a_direct_child_of_the_card(self):
        """mobile.css styles `.card > p`; wrapping it would lose that."""
        html = self.html()
        self.assertRegex(html, r'</div>\s*(?:\{#.*?#\}\s*)?<p class="ds-meta"')

    def test_search_controls_remain_direct_children_of_the_form(self):
        """mobile.css reflows them as flex children of form[method=get]."""
        html = self.html()
        form = html[html.find('<form method="get"'):]
        form = form[:form.find('</form>')]
        self.assertNotIn('<div', form, 'a wrapper would break the mobile reflow')
        for needle in ('name="q"', 'type="submit"', 'btn-secondary', 'link-contrast'):
            self.assertIn(needle, form)

    # -- behaviour must be untouched ---------------------------------
    def test_all_form_fields_and_actions_are_unchanged(self):
        html = self.html()
        self.assertIn('name="drill_ids"', html)
        self.assertIn('name="order[%d]"' % self.did, html)
        self.assertIn('id="selectionOrder"', html)
        self.assertIn('name="selection_order"', html)
        self.assertIn('name="session_title"', html)
        self.assertIn('class="drill-check"', html)
        self.assertIn('class="ds-input order-input"', html)
        self.assertIn('data-drill-id="%d"' % self.did, html)
        self.assertIn('btn-toggle-all', html)
        self.assertIn('id="selCount"', html)
        self.assertIn('data-card-index="0"', html)

    def test_order_input_is_still_a_number_field(self):
        self.assertRegex(self.html(), r'type="number"[^>]*class="ds-input order-input"')


class MobileRulesStillPresentTest(unittest.TestCase):
    """Guard: the desktop cleanup must not have pruned the mobile reflow."""

    def test_key_mobile_selectors_survive(self):
        css = _css(MOBILE_CSS)
        for sel in ('main:has(> .dsm-bar) .card .selection-toolbar',
                    'main:has(> .dsm-bar) #exportForm > .cards + div',
                    'main:has(> .dsm-bar) #exportForm > div:first-of-type',
                    'main:has(> .dsm-bar) .card > p',
                    'main:has(> .dsm-bar) form[method="get"] a.link-contrast'):
            self.assertIn(sel, css, 'mobile rule lost: %s' % sel)

    def test_mobile_partial_still_exists(self):
        path = os.path.join(app.root_path, 'templates', 'mobile', '_drills_select.html')
        self.assertTrue(os.path.exists(path))


if __name__ == '__main__':
    unittest.main()
