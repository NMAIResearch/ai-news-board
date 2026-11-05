"""Execute the generated filter script in Node with a minimal DOM fixture."""

import json
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import unittest

import build
from test_landing_alignment import render_page


DOM_RUNNER = Path(__file__).with_name('filter_dom.js')
DOM_CLASSES = {'f-topic', 'f-tier', 'filter-chip', 'card', 'dayhead'}


class FilterNodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if DOM_CLASSES.intersection(attrs.get('class', '').split()) or attrs.get('id') in {
                'q', 'count', 'conflictonly', 'tiertoggle', 'feed-empty'}:
            self.nodes.append(attrs)


def execute_filters(page, nodes=None):
    if nodes is None:
        parser = FilterNodes(); parser.feed(page); nodes = parser.nodes
    script = re.search(r"\(function\(\)\{\s*var q=document.getElementById\('q'\);.*?\}\)\(\);", page, re.S).group()
    result = subprocess.run(['node', str(DOM_RUNNER)], input=json.dumps({'script': script, 'nodes': nodes}),
                            text=True, capture_output=True, check=True, timeout=10)
    return json.loads(result.stdout), nodes


class NewsFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = render_page()
        cls.output, cls.nodes = execute_filters(cls.page)
        cls.cards = [a for a in cls.nodes if 'card' in a.get('class', '').split()]

    def test_domain_buttons_match_sidebar_topic_identifiers(self):
        domains = {'models': {'models'}, 'hardware': {'power_demand', 'energy_forecast', 'chips'},
                   'regulation': {'regulation'}, 'labour': {'work_automation', 'code_automation', 'cost'}}
        for domain, topics in domains.items():
            expected = [i for i, c in enumerate(self.cards) if topics.intersection(c['data-topics'].split())]
            self.assertEqual(self.output['domains'][domain]['shown'], expected, domain)
            self.assertEqual(self.output['domains'][domain]['query'], '')
        self.assertEqual(self.output['domains']['all']['shown'], list(range(len(self.cards))))
        self.assertEqual(self.output['reset'], list(range(len(self.cards))))
        self.assertGreater(len(self.output['domains']['hardware']['shown']), 0)
        self.assertGreater(len(self.output['domains']['labour']['shown']), 0)

    def test_empty_result_is_visible_and_empty_day_headings_are_hidden(self):
        self.assertEqual(self.output['empty']['shown'], [])
        self.assertTrue(self.output['empty']['messageVisible'])
        self.assertEqual(self.output['empty']['visibleHeadings'], 0)
        self.assertIn('No items match these filters.', self.page)
        self.assertIn('id="feed-empty" role="status"', self.page)

    def test_conflict_filter_uses_disclosures_and_restores_other_records(self):
        expected = [i for i, c in enumerate(self.cards) if c.get('data-conflict') == '1']
        self.assertGreater(len(expected), 0)
        self.assertLess(len(expected), len(self.cards))
        self.assertEqual(self.output['conflicts'], expected)
        self.assertIn('Registry disclosure for OpenAI:', self.page)
        self.assertIn('Registry disclosure for Anthropic:', self.page)

    def test_domains_do_not_match_words_on_unrelated_cards(self):
        nodes = [{'id': 'q'}, {'id': 'count'}, {'id': 'conflictonly'}, {'id': 'feed-empty', 'hidden': None}]
        nodes += [{'class': 'filter-chip', 'data-chip': c} for c in ('all', 'models', 'hardware', 'regulation', 'labour')]
        nodes += [{'class': 'f-topic', 'value': c, 'checked': None} for c in ('models', 'power_demand', 'chips', 'cost', 'regulation', '')]
        nodes += [{'class': 'f-tier', 'value': '5', 'checked': None}, {'class': 'dayhead'}]
        nodes += [{'class': 'card', 'data-topics': topic, 'data-search': words, 'data-tiers': '5'} for topic, words in (
            ('', 'model energy regulation cost'), ('models', 'unrelated text'), ('chips', 'unrelated text'),
            ('power_demand', 'unrelated text'), ('cost', 'unrelated text'), ('regulation', 'unrelated text'))]
        out, _ = execute_filters(self.page, nodes)
        for domain, expected in {'models': [1], 'hardware': [2, 3], 'labour': [4], 'regulation': [5]}.items():
            self.assertEqual(out['domains'][domain]['shown'], expected)
        self.assertEqual(out['conflicts'], [])

    def test_registry_matching_requires_a_recorded_subject_or_publisher(self):
        tier = {'entities': [{'entity': 'Example', 'coi': True, 'basis': 'Recorded stake'},
                             {'entity': 'Another', 'coi': False, 'basis': 'No disclosure'},
                             {'entity': 'Assistant', 'coi': True, 'self': True, 'basis': 'Maker'}]}
        orgs = {'site_org': {'example.test': 'Example'}}
        for item in ({'entity': 'Example'}, {'sources': [{'url': 'https://example.test/post'}]},
                     {'sources': [{'url': 'https://news.example.test/post'}]}):
            self.assertEqual(build.registry_conflicts(item, tier, orgs), ['Registry disclosure for Example: Recorded stake'])
        for item in ({'entity': 'Another'}, {'entity': 'Assistant'}, {'headline': 'Example model'},
                     {'sources': [{'url': 'https://example.test.evil.test/post'}]},
                     {'sources': [{'url': 'https://evil-example.test/post'}]},
                     {'sources': [{'url': 'https://[invalid'}]}):
            self.assertEqual(build.registry_conflicts(item, tier, orgs), [])

    def test_logo_uses_both_assets_and_keeps_accessible_home_link_and_accent(self):
        css = build.LANDING_ALIGNMENT_CSS
        for theme in ('light', 'dark'):
            self.assertIn(f'https://nmairesearch.com/brand/header-nmai-research-{theme}.svg', css)
        self.assertIn(':root[data-theme="dark"] .brand', css)
        self.assertIn(':root:not([data-theme="light"]) .brand', css)
        self.assertIn('@media(forced-colors:active)', css)
        self.assertIn('width:211px;height:36px', css)
        self.assertIn('<a class="brand" href="https://nmairesearch.com/">NMAI Research</a>', self.page)
        self.assertIn('.site-nav a[aria-current]{color:var(--accent);border-bottom:2px solid var(--accent)}', css)


if __name__ == '__main__':
    unittest.main()
