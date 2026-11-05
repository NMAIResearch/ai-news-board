"""Independent negative cases for completion, coverage and public rendering."""

import copy
import contextlib
import html
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import board_checks
import build
import daily_publish
import sovereign_intake as intake
import sovereign_watch as sw
import test_sovereign_intake as fixtures


def complete_store():
    return {'last_run_status': 'complete', 'local_inputs_status': 'ok', 'pending_notifications': [],
            'source_states': {'fixture': {'status': 'ok', 'entries': 1}},
            'document_states': {'doc': {'status': 'evaluated'}},
            'last_pass': {'pending_evaluations': 0, 'manual_review_required': 0, 'documents_deferred': 0,
                          'pending_notifications': 0, 'unhealthy_sources': [], 'not_evaluated_by_reason': {}}}


def end_record(reason='source HTTP status 403'):
    r = {'status': 'pending', 'source_text_sha256': 'b' * 64}
    for n in (1, 2, 3):
        sw.record_document_failure(r, reason, n, True, 'b' * 64 if reason in intake.ASSESSMENT_END_REASONS else None)
    return r


class CompletionContractTests(unittest.TestCase):
    def test_each_completion_clause_refuses_on_its_own(self):
        good = complete_store()
        self.assertTrue(intake.run_is_complete(good))
        board_checks.validate_surveillance_store(good)
        variants = []
        for key, value in [('source_states', {}), ('source_states', {'fixture': {'status': 'failed', 'entries': 1}}),
                           ('local_inputs_status', 'failed'), ('pending_notifications', ['queued'])]:
            s = copy.deepcopy(good); s[key] = value; variants.append(s)
        for key in ('pending_evaluations', 'manual_review_required', 'documents_deferred', 'pending_notifications'):
            for value in (1, None, False, '0'):
                s = copy.deepcopy(good); s['last_pass'][key] = value; variants.append(s)
        s = copy.deepcopy(good); s['document_states']['pending'] = {'status': 'pending'}; variants.append(s)
        s = copy.deepcopy(good); s['last_pass']['not_evaluated_by_reason'] = {'source HTTP status 403': 1}; variants.append(s)
        s = copy.deepcopy(good); s['last_pass']['unhealthy_sources'] = ['fixture']; variants.append(s)
        for state in variants:
            with self.subTest(state=state):
                self.assertFalse(intake.run_is_complete(state))
                self.assertIn('status: incomplete', intake.run_health_text(state))
                with self.assertRaises(board_checks.BoardIntegrityError):
                    board_checks.validate_surveillance_store(state)
        with self.assertRaises(board_checks.BoardIntegrityError):
            board_checks.validate_surveillance_store([])

    def test_empty_source_missing_inventory_and_overdue_end_state_refuse(self):
        for entries in (0, None, False, '1'):
            state = complete_store()
            state['source_states']['fixture']['entries'] = entries
            self.assertFalse(intake.run_is_complete(state))
        state = complete_store(); del state['document_states']
        self.assertFalse(intake.run_is_complete(state))
        state = complete_store(); del state['last_pass']['not_evaluated_by_reason']
        self.assertFalse(intake.run_is_complete(state))
        state = complete_store()
        state['document_states']['end'] = end_record()
        state['last_pass']['not_evaluated_by_reason'] = {'source HTTP status 403': 1}
        for number, valid in ((2, False), (3, True), (9, True), (10, False), (None, False)):
            state['pass_number'] = number
            self.assertEqual(intake.run_is_complete(state), valid)

    def test_end_state_evidence_and_reason_counts_are_required(self):
        for reason in ('source HTTP status 403', 'no AI keyword match', 'model assessment unsuccessful'):
            record = end_record(reason)
            self.assertTrue(intake.valid_end_state(record))
            good = complete_store()
            good['document_states']['end'] = record
            good['pass_number'] = 3
            good['last_pass']['not_evaluated_by_reason'] = {reason: 1}
            self.assertTrue(intake.run_is_complete(good))
            changes = [lambda r: r['end_state'].update(reason='invented'),
                       lambda r: r['end_state'].update(next_check_run=11),
                       lambda r: r['end_state'].update(checked_run=True),
                       lambda r: r['failure_history'].update(runs=[3]),
                       lambda r: r['failure_history'].update(runs=[1, 3, 3]),
                       lambda r: r['failure_history'].update(runs=[3, 2, 1]),
                       lambda r: r['failure_history'].update(runs=[0, 2, 3]),
                       lambda r: r['failure_history'].update(runs=[1, 2, 4]),
                       lambda r: r['failure_history'].update(reason='changed'),
                       lambda r: r.update(status='pending')]
            if reason in intake.ASSESSMENT_END_REASONS:
                changes += [lambda r: r.update(source_text_sha256='c' * 64),
                            lambda r: r['end_state'].update(text_sha256='bad'),
                            lambda r: r['failure_history'].update(text_sha256='c' * 64)]
            for change in changes:
                bad = copy.deepcopy(record); change(bad)
                self.assertFalse(intake.valid_end_state(bad), bad)
                s = copy.deepcopy(good); s['document_states']['end'] = bad
                self.assertFalse(intake.run_is_complete(s))

    def test_unknown_reason_is_refused_when_all_other_evidence_agrees(self):
        record = end_record('invented')
        self.assertEqual(record['failure_history']['reason'], record['end_state']['reason'])
        self.assertFalse(intake.valid_end_state(record))
        state = complete_store()
        state.update(pass_number=3, document_states={'doc': record})
        state['last_pass']['not_evaluated_by_reason'] = {'invented': 1}
        self.assertFalse(intake.run_is_complete(state))
        with self.assertRaises(board_checks.BoardIntegrityError):
            board_checks.validate_surveillance_store(state)

    def test_board_command_and_publisher_invoke_the_store_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'board'
            shutil.copytree(Path(build.HERE), root, ignore=shutil.ignore_patterns('__pycache__'))
            path = root / 'data/surveillance_store.json'
            good = complete_store()
            path.write_text(json.dumps(good))
            with patch.object(board_checks, '__file__', str(root / 'board_checks.py')), \
                 patch.object(daily_publish, 'REPO', root), contextlib.redirect_stdout(io.StringIO()):
                board_checks.main()
                daily_publish.validate_regulatory_alerts()
                good['last_pass']['manual_review_required'] = 1
                path.write_text(json.dumps(good))
                with self.assertRaises(board_checks.BoardIntegrityError):
                    board_checks.main()
                with self.assertRaises(daily_publish.PublishError):
                    daily_publish.validate_regulatory_alerts()


class ValidatorContractTests(unittest.TestCase):
    def assessed(self, **changes):
        cover = {'scope': 'passages only', 'selection_status': 'selected', 'selector': 'ai-keywords-v2',
                 'text_chars': 1000, 'ranges': [[0, 100], [400, 500]], 'passages_total': 3,
                 'passages_read': 2, 'passages_left': 1, 'selected_text_sha256': 'c' * 64}
        cover.update(changes)
        return {'assessment_version': 4, 'evaluation_method': 'local-model', 'source_sha256': 'a' * 64,
                'source_text_sha256': 'b' * 64, 'assessment_coverage': cover}

    def test_each_coverage_clause_refuses_independently(self):
        self.assertTrue(board_checks.valid_assessment_coverage(self.assessed()))
        variants = [dict(passages_total=4), dict(passages_read=1, passages_left=2),
                    dict(ranges=[[1, 100], [400, 500]]), dict(selection_status='not assessed'),
                    dict(selected_text_sha256=intake.digest('')), dict(selector='unknown'),
                    dict(ranges=[[0, 100], [90, 200]]), dict(ranges=[[0, 100], [400, 1001]]),
                    dict(passages_total=True), dict(passages_read=-1, passages_left=4),
                    dict(ranges=[[0, 100], [400, True]]), dict(ranges=[[0, 100], [400]]),
                    dict(ranges='invalid'), dict(text_chars=0), dict(selected_text_sha256='bad')]
        for changes in variants:
            self.assertFalse(board_checks.valid_assessment_coverage(self.assessed(**changes)), changes)
        for changes in ({'assessment_version': 3}, {'evaluation_method': 'unassessed'}, {'source_sha256': None}):
            self.assertFalse(board_checks.valid_assessment_coverage(dict(self.assessed(), **changes)))

    def test_full_and_unassessed_shapes_have_independent_hash_and_count_checks(self):
        full = self.assessed(scope='extracted text', selector='full-text', ranges=[[0, 1000]],
                             passages_total=1, passages_read=1, passages_left=0, selected_text_sha256='b' * 64)
        self.assertTrue(board_checks.valid_assessment_coverage(full))
        for changes in ({'passages_total': 3, 'passages_left': 2}, {'ranges': [[0, 999]]},
                        {'selected_text_sha256': 'c' * 64}, {'selector': 'ai-keywords-v2'}):
            bad = copy.deepcopy(full); bad['assessment_coverage'].update(changes)
            self.assertFalse(board_checks.valid_assessment_coverage(bad))
        unread = self.assessed(scope='unassessed', ranges=[], passages_read=0, passages_left=3,
                               selection_status='not assessed', selected_text_sha256=intake.digest(''))
        unread['evaluation_method'] = 'unassessed'
        self.assertTrue(board_checks.valid_assessment_coverage(unread))
        for changes in ({'selected_text_sha256': 'c' * 64}, {'selection_status': 'selected'},
                        {'ranges': [[0, 100]], 'passages_read': 1, 'passages_left': 2}):
            bad = copy.deepcopy(unread); bad['assessment_coverage'].update(changes)
            self.assertFalse(board_checks.valid_assessment_coverage(bad))


class PublicCoverageTests(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    run_pass = fixtures.PipelineTests.run_pass

    def test_run_totals_match_retained_records_on_all_surfaces(self):
        text = fixtures.TEXT + (' Ordinary details.' * 100 + ' AI requirement applies.') * 45
        self.fetch.return_value = fixtures.feed(2)
        self.capture.return_value = text, 'a' * 64, intake.digest(text)
        self.run_pass()
        state = sw.load_store()
        covs = [r['assessment_coverage'] for r in state['document_states'].values()]
        read = sum(c['passages_read'] for c in covs)
        left = sum(c['passages_left'] for c in covs)
        self.assertGreater(read, 2); self.assertGreater(left, 2)
        self.assertEqual(state['last_pass']['passages_read'], read)
        self.assertEqual(state['last_pass']['passages_left'], left)
        self.assertEqual(state['last_pass']['documents_with_passages_left'], 2)
        line = f'Passages read: {read}; left: {left}.'
        for surface in (build.sovereign_radar_tab(sw.load_alerts(), health=state),
                        sw.write_alert_bulletin(sw.load_alerts(), state).read_text(), self.notify.call_args.args[1]):
            self.assertIn(line, surface)
            self.assertIn('other omitted text is unassessed', surface)
        self.assertEqual(state['last_pass']['passages_only_documents'], 2)
        # Pending assessments retain a known unread count but contribute zero read.
        self.capture.return_value = text + ' Changed.', 'b' * 64, intake.digest(text + ' Changed.')
        self.model.return_value = None
        with self.assertRaises(RuntimeError):
            self.run_pass()
        state = sw.load_store()
        self.assertEqual(state['last_pass']['passages_read'], 0)
        self.assertGreater(state['last_pass']['passages_left'], 0)
        self.assertEqual(state['last_pass']['passages_only_documents'], 0)

    def test_document_counts_and_missing_evidence_are_distinct(self):
        progress = {'passages_read': 7, 'passages_left': 9, 'passages_only_documents': 2,
                    'documents_with_passages_left': 3, 'coverage_not_recorded': 4, 'not_evaluated_by_reason': {}}
        text = intake.run_coverage_text(progress)
        for phrase in ('Passages read: 7; left: 9', 'Passages-only documents: 2',
                       'documents with passages left: 3', 'evaluated documents without passage counts: 4',
                       'Not evaluated by reason: none'):
            self.assertIn(phrase, text)
        text = intake.run_coverage_text({})
        for phrase in ('Passages read: unverified; left: unverified', 'Passages-only documents: unverified',
                       'documents with passages left: unverified', 'without passage counts: unverified',
                       'Not evaluated by reason: unverified'):
            self.assertIn(phrase, text)
        self.run_pass()
        state = sw.load_store()
        self.assertEqual(state['last_pass']['passages_only_documents'], 0)
        record = next(iter(state['document_states'].values()))
        record.pop('assessment_coverage'); record.pop('evaluated_coverage')
        sw.save_store(state)
        with patch.object(sw, 'load_alerts', return_value=[]):
            self.run_pass()
        self.assertEqual(sw.load_store()['last_pass']['coverage_not_recorded'], 1)

    def test_bulletin_refreshes_without_new_alerts_and_states_its_row_limit(self):
        self.run_pass()
        state = sw.load_store(); alert = sw.load_alerts()[0]
        path = sw.write_alert_bulletin([dict(alert, id=f'alert_{n}') for n in range(60)], state)
        self.assertIn('Showing 50 newest records; 10 not shown.', path.read_text())
        self.assertEqual(len([l for l in path.read_text().splitlines() if l.startswith('|')]), 52)
        self.fetch.side_effect = OSError('source unavailable')
        with self.assertRaises(RuntimeError):
            self.run_pass()
        text = path.read_text()
        self.assertIn('status: incomplete', text)
        self.assertIn('Fixture authority: failed', text)
        self.assertIn('Last success:', text)
        self.assertIn('Showing 1 newest records; 0 not shown.', text)
        state['source_states']['fixture'].update(status='limited', limitation='FTC coverage is limited.')
        self.assertIn('FTC coverage is limited.', sw.write_alert_bulletin([alert], state).read_text())

    def test_new_public_fields_escape_markup_and_validate_capture_links(self):
        self.run_pass()
        alert = sw.load_alerts()[0]; state = sw.load_store()
        for url, present in [('https://example.test/a?x="value"', True), ('javascript:alert(1)', False)]:
            page = build.sovereign_radar_tab([dict(alert, source_capture_url=url)], health=state)
            self.assertEqual('Captured source' in page, present)
            if present:
                self.assertIn('href="' + html.escape(url, quote=True) + '"', page)
        state['last_pass']['not_evaluated_by_reason'] = {'<script>alert(1)</script>': 1}
        page = build.sovereign_radar_tab([alert], health=state)
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('Not evaluated documents are listed by reason and are checked again.', page)
        self.assertIn('with passages read and left', page)
        self.model.side_effect = sw.ModelCallError('<script>alert(1)</script>')
        self.capture.return_value = fixtures.TEXT + ' Updated.', 'b' * 64, intake.digest(fixtures.TEXT + ' Updated.')
        with self.assertRaises(RuntimeError):
            self.run_pass()
        page = build.sovereign_radar_tab(sw.load_alerts(), health=sw.load_store())
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('&lt;script&gt;', page)

    def test_markdown_cells_and_links_are_literal(self):
        for char in '|[]*_`\\':
            self.assertIn(f'&#{ord(char)};', sw.markdown_cell('a' + char + 'b'))
        self.assertEqual(sw.markdown_cell('a\n\nb'), 'a b')
        self.assertIn('&lt;img', sw.markdown_cell('<img>'))
        self.run_pass()
        alert = sw.load_alerts()[0]
        for url in ('https://example.test/a|b', 'javascript:alert(1)'):
            text = sw.write_alert_bulletin([dict(alert, url=url)], sw.load_store()).read_text()
            row = [l for l in text.splitlines() if l.startswith('|')][-1]
            self.assertEqual(row.count('|'), 9)
            if url.startswith('https'):
                self.assertIn('a%7Cb', row)
            else:
                self.assertNotIn('javascript:', row)

    def test_failed_local_inputs_prevent_complete_at_the_writer(self):
        with patch.object(sw, 'sweep_local_regulations_packs', side_effect=OSError('unavailable')):
            with self.assertRaises(RuntimeError):
                self.run_pass()
        self.assertEqual(sw.load_store()['last_run_status'], 'incomplete')

    def test_capture_failure_clears_current_coverage_but_keeps_evaluated_evidence(self):
        self.run_pass()
        self.capture.side_effect = OSError('unavailable')
        with self.assertRaises(RuntimeError):
            self.run_pass()
        record = next(iter(sw.load_store()['document_states'].values()))
        self.assertNotIn('assessment_coverage', record)
        self.assertIn('evaluated_coverage', record)

    def test_model_needs_its_full_timeout_and_document_checks_need_reserve(self):
        with patch.object(sw.time, 'monotonic', side_effect=[0, 0, sw.PASS_SECONDS - 60]):
            with self.assertRaises(RuntimeError):
                self.run_pass()
        self.model.assert_not_called()
        self.capture.reset_mock()
        with patch.object(sw.time, 'monotonic', side_effect=[0, sw.PASS_SECONDS - 24]):
            with self.assertRaises(RuntimeError):
                self.run_pass()
        self.capture.assert_not_called()
        self.assertEqual(sw.load_store()['last_pass']['documents_deferred'], 1)

    def test_fixed_run_limits_and_documentation(self):
        self.assertEqual((intake.CAPTURE_FAILURE_RUNS, intake.END_STATE_RECHECK_RUNS), (3, 7))
        self.assertEqual((sw.MAX_DOCUMENT_CHECKS, sw.MAX_MODEL_ATTEMPTS, sw.PASS_SECONDS), (120, 6, 540))
        readme = (Path(build.HERE) / 'README.md').read_text()
        self.assertNotIn('at most 60 documents', readme)
        self.assertIn(f'A pass allows up to {sw.MAX_DOCUMENT_CHECKS} document checks', readme)
        self.assertNotIn('deferred without losing its turn', readme)
        self.assertNotIn('Deferred evaluations retain their order among themselves', readme)


if __name__ == '__main__':
    unittest.main()
