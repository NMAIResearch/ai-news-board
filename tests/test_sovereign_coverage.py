"""Offline coverage, queue end states and public rendering contracts."""

import copy
import html
import http.client
import json
from pathlib import Path
import re
import unittest
import urllib.error
from unittest.mock import patch

import board_checks
import build
import daily_publish
import sovereign_intake as intake
import sovereign_watch as sw
import test_sovereign_intake as fixtures


class CoverageTests(unittest.TestCase):
    def test_opening_and_strong_terms_precede_common_words_with_counts(self):
        text = "Notice of proposed rulemaking. No legal effect. "
        text += ("Ordinary background. " * 100 + "We compute the fee with transparency. ") * 30
        duty = "Artificial intelligence providers shall not disclose personal data."
        text += "Ordinary background. " * 100 + duty
        selected, ranges, counts = intake.select_passages(text, intake.PASSAGE_KEYWORDS, 5000, details=True)
        self.assertTrue(selected.startswith("Notice of proposed rulemaking."))
        self.assertIn(duty, selected)
        self.assertLessEqual(len(selected.encode()), 5000)
        self.assertGreater(counts["passages_left"], 0)
        self.assertEqual(counts["passages_total"], counts["passages_read"] + counts["passages_left"])
        self.assertEqual(counts["passages_read"], len(ranges))
        self.assertEqual(ranges, sorted(ranges))
        self.assertTrue(all(text[b - 1] in ".!?" for _, b in ranges))
        all_text, _, all_counts = intake.select_passages(text, intake.PASSAGE_KEYWORDS, len(text.encode()), details=True)
        self.assertIn(duty, all_text)
        self.assertEqual(all_counts["passages_left"], 0)

    def test_sentence_negation_and_utf8_are_never_cut_for_budget(self):
        text = "Opening notice. " + "Filler details. " * 300 + "AI " + "資料 " * 500 + "shall not apply."
        selected, ranges, counts = intake.select_passages(text, intake.PASSAGE_KEYWORDS, 1700, details=True)
        self.assertNotIn("AI", selected)
        self.assertGreater(counts["passages_left"], 0)
        self.assertLessEqual(len(selected.encode()), 1700)
        self.assertTrue(all(text[b - 1] == "." for _, b in ranges))
        selected, _, counts = intake.select_passages(text, intake.PASSAGE_KEYWORDS, 10000, details=True)
        self.assertIn("shall not apply.", selected)
        self.assertEqual(counts["passages_left"], 0)

    def test_passage_forms_are_separate_from_feed_filter(self):
        for term in ("data center", "data centers", "data centres", "semiconductors", "foundation models",
                     "frontier models", "GPUs", "export controls", "deepfakes", "automated decisions",
                     "AIs", "artificial-intelligence", "machine-learning", "large language model", "chatbot",
                     "DeepMind", "watermarking", "watermarked", "algorithmically"):
            with self.subTest(term=term):
                self.assertIsNotNone(intake.PASSAGE_KEYWORDS.search(term))
        self.assertIsNone(sw.AI_KEYWORDS.search("data centers"))
        self.assertIsNone(intake.PASSAGE_KEYWORDS.search("ordinary public schedule"))

    def test_nonopening_windows_retain_keywords_and_nearby_context(self):
        text = "Ordinary context. " * 180 + "Neighbouring context must be retained. "
        text += "Ordinary context. " * 18 + "AI systems. "
        text += "Ordinary context. " * 45 + "AI systems. "
        text += "Ordinary context. " * 45 + "AI systems. " + "Ordinary context. " * 60
        selected, ranges, _ = intake.select_passages(text, intake.PASSAGE_KEYWORDS, 14000)
        self.assertIn("Neighbouring context must be retained.", selected)
        self.assertTrue(all(a == 0 or intake.PASSAGE_KEYWORDS.search(text[a:b]) for a, b in ranges))

    def test_passage_separators_cost_bytes_at_the_budget_boundary(self):
        text = fixtures.TEXT + " Ordinary details." * 1000 + fixtures.TEXT
        _, spans, _ = intake.select_passages(text, intake.PASSAGE_KEYWORDS, len(text.encode()))
        self.assertGreater(len(spans), 1)
        budget = sum(len(text[a:b].encode()) for a, b in spans)
        selected, bounded, counts = intake.select_passages(text, intake.PASSAGE_KEYWORDS, budget, details=True)
        self.assertLessEqual(len(selected.encode()), budget)
        self.assertLess(len(bounded), len(spans))
        self.assertGreater(counts["passages_left"], 0)

    def test_metadata_and_missing_keywords_do_not_call_model(self):
        for title, text, reason in [("x" * sw.MODEL_INPUT_BYTES, fixtures.TEXT, "input budget too small"),
                                    ("Notice", "Ordinary information. " * 2000, "no AI keyword match")]:
            with self.subTest(reason=reason), patch.object(sw, "call_local_model") as model:
                result = sw.analyze_item_with_model(title, "", "Authority", "https://example.test/doc", source_text=text)
                model.assert_not_called()
                self.assertIn(reason, result["assessment_error"])
                self.assertEqual(result["assessment_coverage"]["passages_read"], 0)

    def test_reference_specificity_keeps_real_references(self):
        text = fixtures.TEXT + " Article 5 applies."
        for reference in (" ", "a", "the", "AI", "Article 5", None):
            with patch.object(sw, "call_local_model", return_value=dict(fixtures.RESULT, statutory_reference=reference)):
                result = sw.analyze_item_with_model("Notice", "", "Authority", "https://example.test/doc", source_text=text)
            self.assertEqual(result["evaluation_method"], "local-model" if reference in ("Article 5", None) else "unassessed")


class StateTests(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    run_pass = fixtures.PipelineTests.run_pass

    def record(self):
        return next(iter(sw.load_store()["document_states"].values()))

    def test_unassessed_has_zero_read_and_reason_on_every_surface(self):
        self.model.side_effect = sw.ModelCallError("model timeout")
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_pass()
        alert = sw.load_alerts()[0]
        coverage = alert["assessment_coverage"]
        self.assertEqual((coverage["scope"], coverage["selection_status"], coverage["ranges"]), ("unassessed", "not assessed", []))
        self.assertEqual((coverage["passages_read"], coverage["passages_left"]), (0, 1))
        for output in (build.sovereign_radar_tab([alert], health=sw.load_store()),
                       next(sw.ALERTS_DIR.glob("*.md")).read_text(), intake.coverage_text(alert)):
            self.assertIn("Coverage: unassessed; not assessed", output)
            self.assertIn("model timeout", output)
            self.assertIn("Passages read: 0; left: 1", output)
            self.assertNotIn("; selected.", output)
        self.model.side_effect = None
        self.run_pass()
        self.assertEqual(self.record()["assessment_coverage"]["passages_read"], 1)

    def test_reverting_text_restores_the_evaluated_coverage(self):
        self.run_pass()
        original = copy.deepcopy(self.record()["assessment_coverage"])
        changed = fixtures.TEXT + " Changed source."
        self.capture.return_value = changed, "b" * 64, intake.digest(changed)
        with patch.object(sw, "MAX_MODEL_ATTEMPTS", 0), self.assertRaises(RuntimeError):
            self.run_pass()
        self.assertNotIn("assessment_coverage", self.record())
        self.assertEqual(self.record()["error"], "evaluation deferred: model call limit")
        self.capture.return_value = fixtures.TEXT, "a" * 64, intake.digest(fixtures.TEXT)
        self.run_pass()
        self.assertEqual(self.record()["assessment_coverage"], original)
        self.assertEqual(self.model.call_count, 1)

    def test_capture_end_state_requires_separate_healthy_runs_and_rechecks(self):
        self.capture.side_effect = urllib.error.HTTPError("https://example.test/doc", 403, "Forbidden", {}, None)
        self.addCleanup(self.capture.side_effect.close)
        for n in range(1, intake.CAPTURE_FAILURE_RUNS):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                self.run_pass()
            self.assertEqual(len(self.record()["failure_history"]["runs"]), n)
            self.assertEqual(self.record()["status"], "pending")
        self.run_pass()
        self.assertTrue(intake.valid_end_state(self.record()))
        self.assertEqual(sw.load_store()["last_pass"]["not_evaluated_by_reason"], {"source HTTP status 403": 1})
        self.model.assert_not_called()
        page = build.sovereign_radar_tab([], health=sw.load_store())
        self.assertIn("status: complete", page)
        self.assertIn("Not evaluated by reason: source HTTP status 403: 1", page)
        captures = self.capture.call_count
        for _ in range(intake.END_STATE_RECHECK_RUNS - 1):
            self.run_pass()
        self.assertEqual(self.capture.call_count, captures)
        self.capture.side_effect = None
        self.run_pass()
        self.assertEqual(self.capture.call_count, captures + 1)
        self.assertEqual(self.record()["status"], "evaluated")
        self.assertNotIn("failure_history", self.record())
        self.assertNotIn("end_state", self.record())

    def test_capture_failures_settle_only_with_healthy_feeds(self):
        for error, feed_error, settle in [(ValueError("insufficient source text"), False, True),
                                          (OSError("connection failed"), False, True),
                                          (ValueError("insufficient source text"), True, False)]:
            sw.save_store({})
            self.capture.side_effect = error
            self.fetch.side_effect = OSError("source offline") if feed_error else None
            if feed_error:
                sw.save_store({"document_states": {"doc": {"status": "pending", "item": {
                    "title": "Notice", "summary": "", "url": "https://example.test/document/0"}, "target": fixtures.TARGET}}})
            for _ in range(3):
                try:
                    self.run_pass()
                except RuntimeError:
                    pass
            self.assertEqual(self.record()["status"] == "not_evaluated", settle)
            self.assertEqual(sw.load_store()["last_run_status"] == "complete", settle)

    def test_two_page_failures_settle_with_a_healthy_feed(self):
        self.fetch.return_value = fixtures.feed(2)
        self.capture.side_effect = ValueError("insufficient source text")
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                self.run_pass()
        self.run_pass()
        self.assertEqual(sw.load_store()["last_pass"]["pending_evaluations"], 0)
        self.assertTrue(all(intake.valid_end_state(r) for r in sw.load_store()["document_states"].values()))

    def test_no_keyword_end_state_reopens_on_changed_text(self):
        text = "Ordinary information. " * 2000
        self.capture.return_value = text, "a" * 64, intake.digest(text)
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                self.run_pass()
        self.run_pass()
        self.assertEqual(self.record()["status"], "not_evaluated")
        self.run_pass()
        self.assertEqual(self.capture.call_count, 3)
        self.capture.return_value = fixtures.TEXT, "b" * 64, intake.digest(fixtures.TEXT)
        for _ in range(intake.END_STATE_RECHECK_RUNS - 1):
            self.run_pass()
        self.assertEqual(self.record()["status"], "evaluated")
        self.assertEqual(self.model.call_count, 1)

    def test_capture_protocol_exception_saves_progress_and_stays_pending(self):
        self.fetch.return_value = fixtures.feed(2)
        self.capture.side_effect = [(fixtures.TEXT, "a" * 64, intake.digest(fixtures.TEXT)), http.client.IncompleteRead(b"part")]
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_pass()
        state = sw.load_store()
        self.assertEqual(state["last_pass"]["pending_evaluations"], 1)
        self.assertEqual(len(sw.load_alerts()), 1)
        self.assertEqual(self.model.call_count, 1)
        self.capture.side_effect = None
        self.run_pass()
        self.assertEqual(len(sw.load_store()["document_states"]), 2)

    def test_retry_turns_and_settled_rechecks_have_distinct_order(self):
        self.model.return_value = None
        with self.assertRaises(RuntimeError):
            self.run_pass()
        self.assertEqual(self.record()["processing_attempts"], 1)
        self.model.return_value = fixtures.RESULT
        self.run_pass()
        self.assertEqual(self.record()["processing_attempts"], 0)
        base = self.record()
        state = sw.load_store()
        state["document_states"] = {
            "a": dict(base, checked_at="2026-10-03", processing_attempts=0),
            "z": dict(base, checked_at="2026-10-01", processing_attempts=99),
        }
        state["document_states"]["a"]["item"] = dict(base["item"], url="https://example.test/a")
        state["document_states"]["z"]["item"] = dict(base["item"], url="https://example.test/z")
        sw.save_store(state)
        self.fetch.side_effect = OSError("feed offline")
        self.capture.reset_mock()
        with patch.object(sw, "MAX_DOCUMENT_CHECKS", 1), self.assertRaises(RuntimeError):
            self.run_pass()
        self.assertEqual(self.capture.call_args.args, ("https://example.test/z",))

    def test_failed_capture_rotates_behind_an_older_pending_attempt(self):
        def record(url, attempts):
            return {"status": "pending", "attempts": attempts, "active": False,
                    "checked_at": "2026-10-01", "target": fixtures.TARGET,
                    "item": {"title": "AI notice", "summary": "", "url": url}}
        sw.save_store({"document_states": {
            "a": record("https://example.test/a", 0), "z": record("https://example.test/z", 1)}})
        self.fetch.return_value = fixtures.feed(0)
        def capture(url):
            if url.endswith("/a"):
                raise OSError("unavailable")
            return fixtures.TEXT, "a" * 64, intake.digest(fixtures.TEXT)
        self.capture.side_effect = capture
        with patch.object(sw, "MAX_DOCUMENT_CHECKS", 1):
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    self.run_pass()
        self.assertEqual(self.capture.call_args_list[-1].args, ("https://example.test/z",))
        self.assertEqual(self.model.call_count, 1)

    def test_slow_model_calls_fit_or_report_deferred_checks(self):
        for seconds, complete in ((0.5, True), (1.25, False)):
            with self.subTest(capture_seconds=seconds):
                self.fetch.return_value = fixtures.feed(120)
                state = {}
                intake.collect_feeds(state, [fixtures.TARGET], self.fetch, sw.AI_KEYWORDS)
                for r in list(state["document_states"].values())[6:]:
                    r.update(status="evaluated", evaluated_text_sha256=intake.digest(fixtures.TEXT))
                sw.save_store(state)
                clock = [0.0]
                def capture(url):
                    clock[0] += seconds
                    return fixtures.TEXT, "a" * 64, intake.digest(fixtures.TEXT)
                def model(*args, **kwargs):
                    self.assertEqual(kwargs["timeout"], 90)
                    clock[0] += 72
                    return fixtures.RESULT
                self.capture.side_effect = capture
                self.model.side_effect = model
                with patch.object(sw.time, "monotonic", side_effect=lambda: clock[0]):
                    if complete:
                        self.run_pass()
                    else:
                        with self.assertRaises(RuntimeError):
                            self.run_pass()
                state = sw.load_store()
                self.assertLessEqual(clock[0], 540)
                self.assertEqual(state["last_pass"]["model_attempts"], 6)
                self.assertEqual(state["last_pass"]["documents_deferred"] == 0, complete)
                self.assertEqual(state["last_run_status"] == "complete", complete)

    def test_ftc_remains_limited_for_empty_response_and_repeated_failures(self):
        target = dict(fixtures.TARGET, id="ftc_press_releases", name="US FTC",
                      failure_coverage="FTC feed unavailable; FTC coverage is limited.")
        sw.save_store({"source_states": {target["id"]: {"last_success": "2026-10-08"}}})
        with patch.object(sw, "REGULATORY_TARGETS", [target]):
            for response in ("<html>unavailable</html>", fixtures.feed(0), fixtures.feed(0)):
                self.fetch.return_value = response
                with self.assertRaises(RuntimeError):
                    self.run_pass()
                state = sw.load_store()
                self.assertEqual(state["last_run_status"], "incomplete")
                page = build.sovereign_radar_tab([], health=state)
                for phrase in ("US FTC: limited", "FTC coverage is limited", "Last success: 2026-10-08"):
                    self.assertIn(phrase, page)
            self.fetch.return_value = fixtures.feed(1)
            self.run_pass()

    def test_forged_complete_fails_gate_and_page(self):
        self.run_pass()
        valid = sw.load_store()
        board_checks.validate_surveillance_store(valid)
        for changes in ({"pending_evaluations": 1}, {"documents_deferred": 1},
                        {"pending_notifications": 1}, {"unhealthy_sources": ["fixture"]}):
            state = copy.deepcopy(valid)
            state["last_pass"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(board_checks.BoardIntegrityError):
                board_checks.validate_surveillance_store(state)
            self.assertIn("status: incomplete", build.sovereign_radar_tab([], health=state))
            sw.save_store(state)
            with patch.object(daily_publish, "REPO", self.root), self.assertRaises(daily_publish.PublishError):
                (self.data / "surveillance_store.json").write_text(json.dumps(state))
                daily_publish.validate_regulatory_alerts()

    def test_coverage_validator_rejects_independent_false_claims(self):
        self.run_pass()
        original = sw.load_alerts()[0]
        cover = original["assessment_coverage"]
        variants = [dict(cover, ranges=[[0, 50]]), dict(cover, selector="wrong"),
                    dict(cover, scope="unknown"), dict(cover, selected_text_sha256="b" * 64),
                    dict(cover, passages_left=2), dict(cover, ranges=[], passages_read=0, passages_left=1),
                    dict(cover, scope="passages only", selector="ai-keywords-v2", passages_total=2,
                         passages_read=2, ranges=[[0, 80], [60, 100]]),
                    dict(cover, scope="passages only", selector="ai-keywords-v2", passages_total=2,
                         passages_read=2, ranges=[[60, 100], [0, 40]])]
        for coverage in variants:
            with self.subTest(coverage=coverage):
                altered = dict(original, assessment_coverage=coverage)
                self.assertFalse(board_checks.valid_assessment_coverage(altered))
                with self.assertRaises(board_checks.BoardIntegrityError):
                    board_checks.validate_regulatory_alerts([altered])
        for version in (None, 3):
            with self.assertRaises(board_checks.BoardIntegrityError):
                board_checks.validate_regulatory_alerts([dict(original, assessment_version=version)])
        unassessed = dict(original, evaluation_method="unassessed", substantive_priority=None,
                          is_operator_duty_shift=False, duty_type="none", denominator_disclosed="unassessed")
        with self.assertRaises(board_checks.BoardIntegrityError):
            board_checks.validate_regulatory_alerts([unassessed])
        valid = dict(cover, scope="unassessed", ranges=[], passages_read=0, passages_left=1,
                     selected_text_sha256=intake.digest(""), selection_status="not assessed")
        unassessed["assessment_coverage"] = valid
        board_checks.validate_regulatory_alerts([unassessed])
        self.assertFalse(board_checks.valid_assessment_coverage(dict(original, assessment_coverage=valid)))

    def test_card_and_bulletin_preserve_all_coverage_and_escape_cells(self):
        text = fixtures.TEXT + " Ordinary details." * 1500 + fixtures.TEXT
        self.capture.return_value = text, "a" * 64, intake.digest(text)
        self.run_pass()
        alert = sw.load_alerts()[0]
        alert.update(summary="First.\n\n<!-- hidden | <img src=x>", statutory_reference="Section [1] | Part *2*")
        page = build.sovereign_radar_tab([alert], health=sw.load_store())
        card = page.split('class="radar-card"', 1)[1]
        bulletin = sw.write_alert_bulletin([alert], sw.load_store()).read_text()
        coverage = alert["assessment_coverage"]
        self.assertGreater(len(coverage["ranges"]), 1)
        for output in (card, html.unescape(bulletin)):
            self.assertIn("Coverage: passages only; selected.", output)
            self.assertNotIn("historical snippet", output)
            self.assertIn(f"Passages read: {coverage['passages_read']}; left: {coverage['passages_left']}", output)
            self.assertIn(f"extracted text length: {len(text)}.", output)
            for start, end in coverage["ranges"]:
                self.assertIn(f"[{start}, {end})", output)
            for value in (alert["source_sha256"], alert["source_text_sha256"], coverage["selected_text_sha256"], str(len(text))):
                self.assertIn(value, output)
        self.assertIn("omitted text is unassessed", page)
        self.assertIn("Captured source", card)
        self.assertIn("Passages-only documents: 1", bulletin)
        rows = [line for line in bulletin.splitlines() if line.startswith("|")]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.count("|") == 9 for row in rows))
        self.assertNotIn("<!--", bulletin)
        self.assertNotIn("<img", bulletin)
        self.assertIn("Showing 1 newest records; 0 not shown", bulletin)

    def test_extracted_text_card_has_its_own_scope_and_equal_hashes(self):
        self.run_pass()
        alert = sw.load_alerts()[0]
        card = build.sovereign_radar_tab([alert], health=sw.load_store()).split('class="radar-card"', 1)[1]
        self.assertIn("Coverage: extracted text; selected.", card)
        self.assertEqual(alert["assessment_coverage"]["selected_text_sha256"], alert["source_text_sha256"])
        self.assertNotIn("Coverage: full text", card)
        self.assertIn("Passages read: 1; left: 0", card)


class ConfigurationTests(unittest.TestCase):
    def test_budget_constants_and_schedule_remain_bounded(self):
        self.assertEqual(sw.MAX_DOCUMENT_CHECKS, 120)
        self.assertEqual(sw.MAX_MODEL_ATTEMPTS, 6)
        self.assertEqual(sw.PASS_SECONDS, 540)
        self.assertEqual(sw.MODEL_INPUT_BYTES, 14848)

    def test_rdf_items_and_invalid_urls(self):
        raw = ('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
               'xmlns="http://purl.org/rss/1.0/"><item><title>AI notice</title>'
               '<link>https://example.test/doc</link></item></rdf:RDF>')
        entries, _ = intake.parse_feed(raw, dict(fixtures.TARGET, format="rss"))
        self.assertEqual(len(entries), 1)
        self.assertTrue(intake.public_url(entries[0]["url"]))
        for url in ("https://example.test/a b", "https://example.test/a\nb", "https://example.test/\x00b"):
            self.assertFalse(intake.public_url(url))


if __name__ == "__main__":
    unittest.main()
