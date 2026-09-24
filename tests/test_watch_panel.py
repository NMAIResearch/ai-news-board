"""Exercise provenance failures, output preservation and calendar boundaries."""

import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build
import watch_panel as watch


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((Path(build.HERE) / 'watch_calendar.json').read_text())

    def test_all_published_schedules_have_sources(self):
        watch.validate_watch(self.data)
        for row in self.data['events']:
            self.assertTrue(row['source_ids'])
            self.assertEqual(row['date_kind'], 'published_schedule')

    def test_malformed_late_rows_fail_closed(self):
        mutations = [
            lambda d: d['events'][-1].update(date='2026-02-30'),
            lambda d: d['events'][-1].update(date_kind='editorial_review'),
            lambda d: d['events'][-1].update(source_ids=['MISSING']),
            lambda d: d['events'][-1].update(source_ids=[]),
            lambda d: d['events'][-1].update(id=d['events'][0]['id']),
            lambda d: d['watches'][-1].update(next_review='2027-09-30T00:00:00Z'),
            lambda d: d['government']['records'][-1].update(source_ids=['MISSING']),
            lambda d: d['government']['records'][-1].update(source_date='unknown'),
            lambda d: d['sources']['BEA'].update(url='javascript:alert(1)'),
            lambda d: d['sources']['BEA'].update(url='http://example.test/'),
            lambda d: d['sources']['BEA'].update(url='https://user:password@example.test'),
            lambda d: d['sources']['BEA'].update(url='https://example.test/\nmalformed'),
        ]
        for mutate in mutations:
            data = copy.deepcopy(self.data)
            mutate(data)
            with self.subTest(mutate=mutate), self.assertRaises(watch.WatchDataError):
                watch.validate_watch(data)

    def test_resolving_requires_a_dated_finding_and_sources(self):
        row = self.data['events'][0]
        row['status'] = 'resolved'
        with self.assertRaises(watch.WatchDataError):
            watch.validate_watch(self.data)
        row['outcome'] = {'finding': 'Synthetic outcome', 'observed_at': '2026-09-24', 'source_ids': ['BEA']}
        watch.validate_watch(self.data)
        self.assertIn('Synthetic outcome', watch.render_watch(self.data))
        row['outcome']['observed_at'] = '2026-09-25'
        with self.assertRaises(watch.WatchDataError):
            watch.validate_watch(self.data)

    def test_passed_date_does_not_resolve_a_question(self):
        self.data['events'][0]['date'] = '2020-01-01'
        rendered = watch.render_watch(self.data)
        self.assertIn('2020-01-01', rendered)
        self.assertNotIn('Resolved with cited evidence', rendered)
        self.assertIn('Unresolved', rendered)

    def test_html_escaping_in_prose_and_source_links(self):
        self.data['events'][0]['title'] = '<script>alert(1)</script>'
        self.data['government']['intro'] = '<img src=x onerror=alert(1)>'
        self.data['sources']['BEA']['url'] = 'https://example.test/?x="&a=<tag>'
        rendered = watch.render_watch(self.data)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('<img', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        self.assertIn('x=&quot;&amp;a=&lt;tag&gt;', rendered)

    def test_ics_is_deterministic_and_excludes_editorial_dates(self):
        first = watch.calendar_ics(self.data)
        self.assertEqual(first, watch.calendar_ics(copy.deepcopy(self.data)))
        self.assertEqual(first.count(b'BEGIN:VEVENT'), len(self.data['events']))
        self.assertNotIn(b'VALARM', first)
        self.assertNotIn(b'20270331', first)
        self.assertNotIn(b'20270930', first)
        self.assertTrue(all(len(line) <= 75 for line in first.split(b'\r\n')))
        unfolded = first.decode().replace('\r\n ', '')
        self.assertEqual(len(set(line for line in unfolded.splitlines() if line.startswith('UID:'))), len(self.data['events']))

    def test_ics_newlines_cannot_inject_events_and_unicode_folds_safely(self):
        self.data['events'][0]['title'] = 'é' * 90 + '\r\nBEGIN:VEVENT\nSUMMARY:injected'
        content = watch.calendar_ics(self.data)
        content.decode('utf-8')
        self.assertNotIn(b'\n', content.replace(b'\r\n', b''))
        self.assertNotIn(b'\r', content.replace(b'\r\n', b''))
        self.assertTrue(all(len(line) <= 75 for line in content.split(b'\r\n')))
        self.assertEqual(content.count(b'\r\nBEGIN:VEVENT\r\n'), len(self.data['events']))

    def test_invalid_input_preserves_existing_outputs(self):
        self.data['government']['records'][-1]['source_ids'] = ['MISSING']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'watch_calendar.json').write_text(json.dumps(self.data))
            (root / 'index.html').write_text('existing page')
            (root / 'AI_OUTLOOK.ics').write_text('existing calendar')
            with patch.object(build, 'HERE', directory), patch.object(build, 'OUT', str(root / 'index.html')):
                with self.assertRaises(watch.WatchDataError):
                    build.main()
            self.assertEqual((root / 'index.html').read_text(), 'existing page')
            self.assertEqual((root / 'AI_OUTLOOK.ics').read_text(), 'existing calendar')

    def test_missing_input_stops_build(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(build, 'HERE', directory):
            with self.assertRaises(FileNotFoundError):
                build.main()

    def test_both_build_modes_keep_watch_and_archive_separate(self):
        for argv in (['build.py'], ['build.py', '--plain']):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'index.html'
                with patch.object(build, 'OUT', str(output)), patch('sys.argv', argv):
                    with contextlib.redirect_stdout(io.StringIO()):
                        build.main()
                page = output.read_text()
                self.assertIn('data-target="tab-reference">Watch</button>', page)
                self.assertIn('data-watch-jump', page)
                self.assertIn('Dated archive: earlier roster', page)
                self.assertLess(page.index('US government roles in AI:'), page.index('Dated archive: earlier roster'))
                self.assertIn('Historical gauge readings', page)
                self.assertEqual(output.with_name('AI_OUTLOOK.ics').read_bytes(), watch.calendar_ics(self.data))
                watch.validate_watch_outputs(self.data, output.parent)

    def test_parity_checks_reject_missing_stale_and_duplicate_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / 'index.html'
            ics = root / 'AI_OUTLOOK.ics'
            with self.assertRaisesRegex(watch.WatchDataError, 'unavailable'):
                watch.validate_watch_outputs(self.data, root)
            expected_page = '<main>' + watch.watch_fragment(self.data) + '</main>'
            expected_ics = watch.calendar_ics(self.data)
            page.write_text(expected_page, encoding='utf-8')
            ics.write_bytes(expected_ics)
            watch.validate_watch_outputs(self.data, root)
            cases = [
                ('calendar', expected_page, b'stale calendar'),
                ('page', expected_page.replace('Watch: evidence', 'Stale: evidence'), expected_ics),
                ('missing marker', expected_page.replace(watch.WATCH_END, ''), expected_ics),
                ('duplicate marker', expected_page + watch.WATCH_END, expected_ics),
                ('reversed markers', watch.WATCH_END + watch.WATCH_START, expected_ics),
            ]
            for label, html, content in cases:
                page.write_text(html, encoding='utf-8')
                ics.write_bytes(content)
                before = (page.read_bytes(), ics.read_bytes())
                with self.subTest(label=label), self.assertRaises(watch.WatchDataError):
                    watch.validate_watch_outputs(self.data, root)
                self.assertEqual(before, (page.read_bytes(), ics.read_bytes()))

    def test_board_check_command_refuses_stale_exports_until_rebuilt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'board'
            shutil.copytree(Path(build.HERE), root, ignore=shutil.ignore_patterns('.git', '__pycache__'))
            def run(script):
                return subprocess.run([sys.executable, script], cwd=root,
                                      text=True, capture_output=True, timeout=30)
            self.assertEqual(run('build.py').returncode, 0)
            self.assertEqual(run('board_checks.py').returncode, 0)
            source = root / 'watch_calendar.json'
            changed = copy.deepcopy(self.data)
            changed['events'][0]['date'] = '2027-02-03'
            source.write_text(json.dumps(changed), encoding='utf-8')
            stale = run('board_checks.py')
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn('AI_OUTLOOK.ics differs', stale.stderr)
            (root / 'AI_OUTLOOK.ics').write_bytes(watch.calendar_ics(changed))
            stale_page = run('board_checks.py')
            self.assertNotEqual(stale_page.returncode, 0)
            self.assertIn('Watch HTML differs', stale_page.stderr)
            self.assertEqual(run('build.py').returncode, 0)
            self.assertEqual(run('board_checks.py').returncode, 0)


if __name__ == '__main__':
    unittest.main()
