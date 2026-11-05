"""Persistent failures, healthy feed evidence and bounded recovery paths."""

import copy
import contextlib
import http.client
import io
import json
import sys
import unittest
import urllib.error
from unittest.mock import patch

import board_checks
import build
import sovereign_intake as intake
import sovereign_watch as sw
import test_sovereign_intake as fixtures


class SettlementTests(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    run_pass = fixtures.PipelineTests.run_pass

    def record(self):
        return next(iter(sw.load_store()['document_states'].values()))

    def pending(self):
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            self.run_pass()
        self.assertEqual(sw.load_store()['last_run_status'], 'incomplete')

    def qualify(self):
        for number in (1, 2):
            self.pending()
            self.assertFalse(intake.valid_end_state(self.record()))
            self.assertEqual(len(self.record()['failure_history']['runs']), number)
        self.run_pass()
        self.assertTrue(intake.valid_end_state(self.record()))
        self.assertEqual(self.record()['status'], 'not_evaluated')
        state = sw.load_store()
        self.assertEqual(state['last_pass']['pending_evaluations'], 0)
        self.assertEqual(state['last_pass']['manual_review_required'], 0)
        board_checks.validate_surveillance_store(state)
        reason = self.record()['end_state']['reason']
        for surface in (build.sovereign_radar_tab(sw.load_alerts(), health=state),
                        sw.write_alert_bulletin(sw.load_alerts(), state).read_text()):
            self.assertIn('status: complete', surface)
            self.assertIn(reason + ': 1', surface)

    def test_all_capture_failure_kinds_qualify_and_success_reopens(self):
        errors = [ValueError('source response exceeds byte limit'),
                  UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid'),
                  ValueError('source returned an error or access challenge'),
                  ValueError('insufficient source text'), ValueError('source document is unavailable'),
                  ValueError('other capture failure'), OSError('unavailable'), TimeoutError('timeout'),
                  http.client.IncompleteRead(b'part'), http.client.BadStatusLine('invalid')]
        errors += [urllib.error.HTTPError('https://example.test/doc', code, 'Unavailable', {}, None)
                   for code in (401, 403, 404, 410, 451, 429, 500, 503)]
        for error in errors:
            with self.subTest(error=repr(error)):
                sw.save_store({})
                self.capture.side_effect = error
                self.qualify()
                self.assertEqual(self.record()['end_state']['next_check_run'], 10)
                count = self.capture.call_count
                for _ in range(6):
                    self.run_pass()
                self.assertEqual(self.capture.call_count, count)
                self.capture.side_effect = None
                self.run_pass()
                self.assertEqual(self.capture.call_count, count + 1)
                self.assertEqual(self.record()['status'], 'evaluated')
                self.assertNotIn('end_state', self.record())
                self.assertNotIn('failure_history', self.record())

    def test_assessment_failures_qualify_and_recheck_one_call_every_seven_runs(self):
        for reply in (None, dict(fixtures.RESULT, evidence_quote='This quote is absent from the document.')):
            with self.subTest(reply=reply):
                sw.save_store({})
                self.model.reset_mock()
                self.model.return_value = reply
                self.qualify()
                self.assertEqual(self.model.call_count, 3)
                for _ in range(6):
                    self.run_pass()
                self.assertEqual(self.model.call_count, 3)
                self.run_pass()
                self.assertEqual(self.model.call_count, 4)
                self.assertEqual(self.record()['end_state']['next_check_run'], 17)
                for _ in range(6):
                    self.run_pass()
                self.model.return_value = dict(fixtures.RESULT)
                self.run_pass()
                self.assertEqual(self.model.call_count, 5)
                self.assertEqual(self.record()['status'], 'evaluated')
                self.assertNotIn('failure_history', self.record())

    def test_model_transport_failure_also_settles(self):
        self.model.side_effect = sw.ModelCallError('model timeout')
        self.qualify()
        self.assertEqual(self.model.call_count, 3)
        self.assertEqual(self.record()['end_state']['reason'], 'model assessment unsuccessful')

    def test_budget_and_keyword_failures_qualify_without_model_calls(self):
        for text in ('AI schedule ' * 3000 + '.', 'Ordinary information. ' * 2000):
            with self.subTest(text=text[:20]):
                sw.save_store({})
                self.capture.return_value = text, 'a' * 64, intake.digest(text)
                self.qualify()
                self.assertEqual(self.record()['assessment_coverage']['passages_read'], 0)
                self.assertGreater(self.record()['assessment_coverage']['passages_left'], 0)
                self.model.assert_not_called()
                for _ in range(6):
                    self.run_pass()
                self.capture.return_value = fixtures.TEXT, 'b' * 64, intake.digest(fixtures.TEXT)
                self.run_pass()
                self.assertEqual(self.record()['status'], 'evaluated')
                self.model.reset_mock()

    def test_metadata_budget_failure_qualifies_and_recovers(self):
        feed = json.loads(fixtures.feed())
        feed['results'][0]['title'] = 'AI ' * sw.MODEL_INPUT_BYTES
        self.fetch.return_value = json.dumps(feed)
        self.qualify()
        self.assertEqual(self.record()['end_state']['reason'], 'input budget too small')
        self.model.assert_not_called()
        for _ in range(6):
            self.run_pass()
        self.fetch.return_value = fixtures.feed()
        self.run_pass()
        self.assertEqual(self.record()['status'], 'evaluated')

    def test_one_wrong_page_preserves_evaluation_and_recovers_next_run(self):
        self.run_pass()
        prior = copy.deepcopy(sw.load_alerts()[0])
        coverage = copy.deepcopy(self.record()['evaluated_coverage'])
        text = 'Content has moved. Please browse the site. ' * 800
        self.capture.return_value = text, 'b' * 64, intake.digest(text)
        self.pending()
        self.assertFalse(intake.valid_end_state(self.record()))
        self.assertIn(prior, sw.load_alerts())
        self.assertEqual(self.record()['evaluated_coverage'], coverage)
        self.capture.return_value = fixtures.TEXT, 'a' * 64, intake.digest(fixtures.TEXT)
        self.run_pass()
        self.assertEqual(self.record()['status'], 'evaluated')
        self.assertEqual(self.record()['assessment_coverage'], coverage)
        self.assertEqual(self.model.call_count, 1)

    def test_new_reason_or_new_text_starts_a_new_qualification(self):
        self.capture.side_effect = ValueError('insufficient source text')
        self.pending()
        self.pending()
        self.capture.side_effect = TimeoutError()
        self.pending()
        self.assertEqual(self.record()['failure_history']['runs'], [3])
        self.capture.side_effect = None
        self.model.return_value = None
        self.pending()
        self.pending()
        self.capture.return_value = fixtures.TEXT + ' Change.', 'b' * 64, intake.digest(fixtures.TEXT + ' Change.')
        self.pending()
        self.assertEqual(self.record()['failure_history']['runs'], [6])

    def test_feed_outage_does_not_qualify_capture_or_assessment_failures(self):
        for capture_error in (True, False):
            with self.subTest(capture_error=capture_error):
                sw.save_store({})
                self.fetch.side_effect = None
                self.capture.side_effect = ValueError('insufficient source text') if capture_error else None
                self.model.return_value = None
                self.pending()
                self.fetch.side_effect = OSError('feed unavailable')
                for _ in range(4):
                    self.pending()
                    self.assertNotIn('failure_history', self.record())
                    self.assertFalse(intake.valid_end_state(self.record()))
                self.fetch.side_effect = None
                for _ in range(2):
                    self.pending()
                self.run_pass()
                self.assertTrue(intake.valid_end_state(self.record()))

    def test_capture_success_resets_strikes_even_if_model_work_is_deferred(self):
        self.model.return_value = None
        self.pending()
        self.capture.side_effect = OSError('unavailable')
        self.pending(); self.pending()
        self.capture.side_effect = None
        with patch.object(sw, 'MAX_MODEL_ATTEMPTS', 0):
            self.pending()
        self.assertNotIn('failure_history', self.record())
        self.capture.side_effect = OSError('unavailable')
        self.pending()
        self.assertEqual(self.record()['failure_history']['runs'], [5])

    def test_different_capture_error_starts_a_new_history(self):
        self.capture.side_effect = OSError('connection failure')
        self.pending(); self.pending()
        self.capture.side_effect = TimeoutError('timeout')
        self.pending()
        self.assertEqual(self.record()['failure_history']['runs'], [3])

    def test_failure_history_compares_text_even_when_called_directly(self):
        record = {'status': 'pending'}
        for number in (1, 2):
            sw.record_document_failure(record, 'model assessment unsuccessful', number, True, 'a' * 64)
        sw.record_document_failure(record, 'model assessment unsuccessful', 3, True, 'b' * 64)
        self.assertEqual(record['failure_history']['runs'], [3])

    def test_capture_reasons_describe_the_observed_failure_kind(self):
        self.assertEqual(sw.capture_failure_reason(UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid')),
                         'source response is not UTF-8')
        for reason in ('source response exceeds byte limit', 'source returned an error or access challenge',
                       'insufficient source text', 'source document is unavailable'):
            self.assertEqual(sw.capture_failure_reason(ValueError(reason)), reason)
        self.assertEqual(sw.capture_failure_reason(OSError('private details')), 'source capture failed')
        for code in (401, 403, 404, 410, 451, 500):
            error = urllib.error.HTTPError('https://example.test/doc', code, 'unavailable', {}, None)
            self.addCleanup(error.close)
            self.assertEqual(sw.capture_failure_reason(error), f'source HTTP status {code}')

    def test_duplicate_run_number_does_not_earn_three_strikes(self):
        record = {'status': 'pending'}
        for _ in range(4):
            sw.record_document_failure(record, 'insufficient source text', 1, True)
        self.assertEqual(record['failure_history']['runs'], [1])
        self.assertFalse(intake.valid_end_state(record))

    def test_old_or_forged_end_states_reopen_even_when_no_checks_fit(self):
        self.run_pass()
        state = sw.load_store()
        record = next(iter(state['document_states'].values()))
        record.update(status='not_evaluated', end_state={'reason': 'no AI keyword match',
                      'checked_run': 1, 'next_check_run': 8, 'text_sha256': record['source_text_sha256']})
        sw.save_store(state)
        with patch.object(sw, 'MAX_DOCUMENT_CHECKS', 0):
            self.pending()
        self.assertEqual(self.record()['status'], 'pending')
        self.assertNotIn('end_state', self.record())

    def test_source_outage_keeps_an_earned_end_state_run_incomplete(self):
        self.capture.side_effect = ValueError('insufficient source text')
        self.qualify()
        self.fetch.return_value = fixtures.feed(0)
        self.pending()
        self.assertNotEqual(sw.load_store()['source_states']['fixture']['status'], 'ok')

    def test_unchanged_failure_does_not_rewrite_alert_timestamp_or_event_log(self):
        self.model.return_value = None
        self.pending()
        first = sw.ALERTS_FILE.read_bytes()
        events = sw.ALERTS_LOG.read_bytes()
        self.pending()
        self.run_pass()
        self.assertEqual(sw.ALERTS_FILE.read_bytes(), first)
        self.assertEqual(sw.ALERTS_LOG.read_bytes(), events)

    def test_abort_marks_new_attempt_incomplete_and_status_checks_evidence(self):
        self.run_pass()
        with patch.object(sw, 'sweep_sovereign_gazettes', side_effect=RuntimeError('unexpected abort')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected abort'):
                self.run_pass()
        state = sw.load_store()
        self.assertEqual(state['last_run_status'], 'incomplete')
        self.assertEqual(state['last_pass'], {})
        self.assertIn('Failed or limited sources: unverified', intake.run_health_text(state))
        self.assertIn('status: incomplete', build.sovereign_radar_tab(sw.load_alerts(), health=state))
        state['last_run_status'] = 'complete'
        sw.save_store(state)
        with patch.object(sys, 'argv', ['sovereign_watch.py', '--status']), contextlib.redirect_stdout(io.StringIO()) as out:
            sw.main()
        self.assertIn('Last pass status: incomplete', out.getvalue())

    def test_model_json_resource_limits_are_failed_assessments(self):
        for payload in ('{"value":' + '9' * 5000 + '}',):
            self.assertIsNone(sw.parse_llm_json_response(payload))
            for raw in (payload.encode(), json.dumps({'message': {'content': payload}}).encode()):
                response = unittest.mock.MagicMock()
                response.__enter__.return_value.read.return_value = raw
                with patch.object(sw.urllib.request, 'urlopen', return_value=response):
                    with self.assertRaises(sw.ModelCallError):
                        self.real_model_call('Evaluate this text.')
        self.assertEqual(sw.parse_llm_json_response('{"value": 1}'), {'value': 1})

    def test_protocol_errors_preserve_earlier_evaluations_in_the_pass(self):
        self.fetch.return_value = fixtures.feed(2)
        for failure in (http.client.IncompleteRead(b'part'), http.client.BadStatusLine('invalid')):
            sw.save_store({})
            with patch.object(sw, 'call_local_model', wraps=self.real_model_call) as model:
                # The first response is valid; the second fails in the actual transport handler.
                payload = json.dumps({'message': {'content': json.dumps(fixtures.RESULT)}}).encode()
                response = unittest.mock.MagicMock()
                response.__enter__.return_value.read.return_value = payload
                with patch.object(sw.urllib.request, 'urlopen', side_effect=[response, failure]):
                    self.pending()
            self.assertEqual(model.call_count, 2)
            self.assertEqual(sw.load_store()['last_pass']['pending_evaluations'], 1)
            self.assertEqual(sum(r['status'] == 'evaluated' for r in sw.load_store()['document_states'].values()), 1)

    real_model_call = staticmethod(sw.call_local_model)


class FeedEvidenceTests(unittest.TestCase):
    def test_every_empty_feed_keeps_previous_success_and_active_records(self):
        for target in sw.REGULATORY_TARGETS:
            with self.subTest(source=target['id']):
                state = {'source_states': {target['id']: {'last_success': 'earlier'}}, 'document_states': {
                    'doc': {'status': 'evaluated', 'target': target, 'active': True}}}
                body = ('{"results": []}' if target['format'] == 'json_fedreg' else
                        '<feed xmlns="http://www.w3.org/2005/Atom"/>' if target['format'] == 'atom' else '<rss><channel/></rss>')
                intake.collect_feeds(state, [target], lambda _: body, sw.AI_KEYWORDS)
                source = state['source_states'][target['id']]
                self.assertNotEqual(source['status'], 'ok')
                self.assertEqual(source['last_success'], 'earlier')
                self.assertTrue(state['document_states']['doc']['active'])

    def test_nonempty_feed_with_no_matching_current_items_is_healthy(self):
        state = {}
        intake.collect_feeds(state, [fixtures.TARGET], lambda _: fixtures.rollover_feed(), sw.AI_KEYWORDS)
        self.assertEqual(state['source_states']['fixture']['status'], 'ok')
        self.assertEqual(state['document_states'], {})

    def test_null_or_malformed_entry_fields_fail_closed_without_abort(self):
        for change in ({'title': None}, {'html_url': 'https://[invalid'}, {'abstract': 123}, {'publication_date': []}):
            feed = json.loads(fixtures.feed())
            feed['results'][0].update(change)
            state = {}
            intake.collect_feeds(state, [fixtures.TARGET], lambda _: json.dumps(feed), sw.AI_KEYWORDS)
            self.assertEqual(state['source_states']['fixture']['status'], 'failed')
        for doc in (None, 42, []):
            with self.assertRaises(ValueError):
                intake.parse_feed(json.dumps({'results': [doc]}), fixtures.TARGET)

    def test_extractor_uses_body_when_the_preferred_element_is_too_short(self):
        self.assertEqual(intake.document_text('<article>Related item</article><div>' + fixtures.TEXT + '</div>'),
                         'Related item ' + fixtures.TEXT)
        self.assertEqual(intake.document_text('<nav>Site furniture</nav><main>' + fixtures.TEXT + '</main>'), fixtures.TEXT)
        with self.assertRaisesRegex(ValueError, 'insufficient source text'):
            intake.document_text('<article>Short</article>')
        notice = 'Applicants may request access to the AI dataset. ' + fixtures.TEXT
        self.assertEqual(intake.document_text('<main>' + notice + '</main>'), notice)
        for heading in ('Request Access', 'Page not found', 'Verify you are human'):
            with self.assertRaisesRegex(ValueError, 'challenge'):
                intake.document_text('<main>' + heading + '. ' + fixtures.TEXT + '</main>')


class PassageBoundaryTests(unittest.TestCase):
    def test_abbreviations_do_not_detach_the_following_negation(self):
        for reference in ('15 U.S.C. 1681 and Sec. 5', 'Art. 5', 'No. 14', 'Dr. A. Person', 'i.e. covered firms'):
            sentence = 'Every covered operator shall, under ' + reference + ', not be required to disclose outputs.'
            text = 'Opening notice. ' + 'Ordinary details. ' * 1000 + 'AI applies. ' + 'x' * 470 + ' ' + sentence + ' More details. ' * 200
            selected, ranges, _ = intake.select_passages(text, intake.PASSAGE_KEYWORDS, 5000)
            self.assertIn(sentence, selected)
            self.assertTrue(all(not text[a:b].endswith(('U.S.C.', 'Sec.', 'Art.', 'No.', 'i.e.')) for a, b in ranges))

    def test_no_keyword_selection_still_counts_the_unread_opening(self):
        selected, ranges, counts = intake.select_passages('Ordinary details. ' * 1000,
                                                          intake.PASSAGE_KEYWORDS, 5000, details=True)
        self.assertEqual((selected, ranges), ('', []))
        self.assertEqual(counts, {'passages_total': 1, 'passages_read': 0, 'passages_left': 1, 'matched': False})

    def test_opening_too_large_is_not_silently_skipped(self):
        text = 'No sentence end but AI words ' * 900 + '. Later AI duty applies.'
        selected, ranges, counts = intake.select_passages(text, intake.PASSAGE_KEYWORDS, 500, details=True)
        self.assertEqual((selected, ranges), ('', []))
        self.assertGreater(counts['passages_left'], 0)

    def test_specific_references_require_a_provision_or_instrument(self):
        for reference in ('of', 'e', 's', '5', '.', 'to', 'with', 'Operators', 'number', 'AI', ' '):
            self.assertFalse(sw.specific_reference(reference), reference)
        for reference in ('Article 5', 'section 202(d)', '42 U.S.C. 18841', '34 CFR part 602',
                          'Federal Advisory Committee Act', 'Regulation (EU) 2024/1689', 'FR Doc. 2026-17842'):
            self.assertTrue(sw.specific_reference(reference), reference)
        text = fixtures.TEXT + ' Article 5 applies.'
        for reference in ('of', 'Article 5', 'Section 99'):
            with patch.object(sw, 'call_local_model', return_value=dict(fixtures.RESULT, statutory_reference=reference)):
                answer = sw.analyze_item_with_model('Notice', '', 'Authority', 'https://example.test/doc', source_text=text)
            self.assertEqual(answer['evaluation_method'], 'local-model' if reference == 'Article 5' else 'unassessed')


if __name__ == '__main__':
    unittest.main()
