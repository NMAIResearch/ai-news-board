"""Offline regressions for limited sources, passage coverage and durable retries."""

import copy
import json
import unittest
from unittest.mock import patch

import board_checks
import build
import sovereign_intake as intake
import sovereign_watch as sw
import test_sovereign_intake as fixtures

CAPTURE_SOURCE = sw.capture_source


class RepairPipelineTests(unittest.TestCase):
    run_pass = fixtures.PipelineTests.run_pass

    def setUp(self):
        fixtures.PipelineTests.setUp(self)
        self.stack.enter_context(patch.object(sw, "SOURCE_CACHE", self.root / "sources"))

    def raw_source(self, raw):
        self.capture.side_effect = CAPTURE_SOURCE
        self.fetch.side_effect = lambda url: fixtures.feed() if url == fixtures.TARGET["url"] else raw

    def test_ftc_failure_is_limited_and_visible_without_alerts(self):
        target = next(t for t in sw.REGULATORY_TARGETS if t["id"] == "fixture")
        target = dict(target, id="ftc_press_releases", name="US FTC",
                      failure_coverage="FTC feed unavailable; FTC coverage is limited.")
        sw.save_store({"source_states": {target["id"]: {"last_success": "2026-10-08"}}})
        self.fetch.side_effect = OSError("fixture unavailable")
        with patch.object(sw, "REGULATORY_TARGETS", [target]), self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_pass()
        state = sw.load_store()
        self.assertEqual(state["source_states"][target["id"]]["status"], "limited")
        self.assertEqual(state["source_states"][target["id"]]["last_success"], "2026-10-08")
        self.assertEqual(state["last_pass"]["unhealthy_sources"], [target["id"]])
        self.assertNotIn("last_complete_run", state)
        page = build.sovereign_radar_tab([], health=state)
        self.assertIn("FTC coverage is limited", page)
        self.assertIn("status: incomplete", page)
        self.assertNotIn("fixture unavailable", page)

    def test_ftc_recovery_requires_a_valid_feed(self):
        target = dict(fixtures.TARGET, id="ftc_press_releases", name="US FTC",
                      failure_coverage="FTC feed unavailable; FTC coverage is limited.")
        self.fetch.return_value = "<html>Not a feed</html>"
        with patch.object(sw, "REGULATORY_TARGETS", [target]):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                self.run_pass()
            self.fetch.return_value = fixtures.feed(1)
            self.run_pass()
        state = sw.load_store()
        self.assertEqual(state["last_run_status"], "complete")
        self.assertEqual(state["source_states"][target["id"]]["status"], "ok")
        self.assertNotIn("limitation", state["source_states"][target["id"]])

    def test_long_capture_keeps_original_and_bounded_passage_provenance(self):
        raw = "<main>" + "Ordinary background information. " * 4500 + fixtures.TEXT + "</main>"
        self.raw_source(raw)
        def bounded(prompt, **kwargs):
            self.assertLessEqual(len(prompt.encode("utf-8")), sw.MODEL_INPUT_BYTES)
            self.assertIn("Coverage: passages only", prompt)
            return dict(fixtures.RESULT)
        self.model.side_effect = bounded
        self.run_pass()
        alert = sw.load_alerts()[0]
        text = intake.document_text(raw)
        coverage = alert["assessment_coverage"]
        self.assertGreater(len(text), intake.MAX_TEXT_CHARS)
        self.assertEqual(coverage["scope"], "passages only")
        selected = intake.PASSAGE_SEPARATOR.join(text[start:end] for start, end in coverage["ranges"])
        self.assertIn(fixtures.QUOTE, selected)
        self.assertEqual(coverage["selected_text_sha256"], intake.digest(selected))
        self.assertEqual(alert["source_sha256"], intake.digest(raw))
        self.assertEqual(alert["source_text_sha256"], intake.digest(text))
        self.assertEqual((sw.SOURCE_CACHE / (intake.digest(raw) + ".html")).read_text(), raw)
        self.assertEqual((sw.SOURCE_CACHE / (intake.digest(raw) + ".txt")).read_text(), text)
        record = next(iter(sw.load_store()["document_states"].values()))
        self.assertEqual(record["assessment_coverage"], coverage)
        event = json.loads(sw.ALERTS_LOG.read_text().splitlines()[0])
        self.assertEqual(event["assessment_coverage"], coverage)
        page = build.sovereign_radar_tab([alert], health=sw.load_store())
        bulletin = next(sw.ALERTS_DIR.glob("*.md")).read_text()
        for rendered in (page, bulletin):
            self.assertIn("Coverage: passages only; selected.", rendered)
            self.assertIn("zero-based, end-exclusive", rendered)
            self.assertIn(str(coverage["ranges"][0][0]), rendered)
            self.assertIn(alert["source_sha256"], rendered)
        calls = self.model.call_count
        self.run_pass()
        self.assertEqual(self.model.call_count, calls)

    def test_long_document_without_keyword_stays_explicitly_unassessed(self):
        self.raw_source("<main>" + "Ordinary background information. " * 4500 + "</main>")
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                self.run_pass()
        self.run_pass()
        self.model.assert_not_called()
        alert = sw.load_alerts()[0]
        self.assertEqual(alert["assessment_coverage"]["scope"], "unassessed")
        self.assertEqual(alert["assessment_coverage"]["ranges"], [])
        self.assertEqual(alert["evaluation_method"], "unassessed")
        self.assertIsNone(board_checks.evaluated_alert_priority(alert))
        state = sw.load_store()
        self.assertEqual(state["last_pass"]["pending_evaluations"], 0)
        self.assertEqual(state["last_pass"]["manual_review_required"], 0)
        self.assertEqual(state["last_pass"]["not_evaluated_by_reason"], {"no AI keyword match": 1})
        self.assertIn("Not evaluated by reason: no AI keyword match: 1", build.sovereign_radar_tab([alert], health=state))
        self.assertTrue(intake.valid_end_state(next(iter(state["document_states"].values()))))

    def test_quotes_and_references_must_be_in_a_selected_source_range(self):
        outside = "This separate introductory sentence is outside the selected passages."
        text = "Ordinary background information. " * 400 + outside + " Ordinary background information." * 900 + fixtures.TEXT
        self.capture.return_value = (text, "a" * 64, intake.digest(text))
        for changes in ({"evidence_quote": outside}, {"statutory_reference": outside},
                        {"evidence_quote": "A made up passage that appears nowhere in the source."}):
            self.model.return_value = dict(fixtures.RESULT, **changes)
            sw.save_store({})
            with self.subTest(changes=changes), self.assertRaisesRegex(RuntimeError, "incomplete"):
                self.run_pass()
            self.assertEqual(sw.load_alerts()[0]["evaluation_method"], "unassessed")
            self.assertNotIn("last_complete_run", sw.load_store())

    def test_version_four_coverage_cannot_be_missing_or_invalid(self):
        self.run_pass()
        original = sw.load_alerts()[0]
        variants = [None, {}, dict(original["assessment_coverage"], ranges=[[0, 1000000]]),
                    dict(original["assessment_coverage"], ranges=[[False, 10]]),
                    dict(original["assessment_coverage"], selected_text_sha256="invalid"),
                    dict(original["assessment_coverage"], scope="passages only", selector="ai-keywords-v1", ranges=[])]
        for coverage in variants:
            alert = dict(original, assessment_coverage=coverage)
            with self.subTest(coverage=coverage):
                self.assertFalse(board_checks.has_valid_alert_evaluation(alert))
                with self.assertRaises(board_checks.BoardIntegrityError):
                    board_checks.validate_regulatory_alerts([alert])
        board_checks.validate_regulatory_alerts([original])

    def test_existing_manual_backlog_drains_without_losing_off_feed_records(self):
        text = "Ordinary background information. " * 1000 + fixtures.TEXT
        self.capture.return_value = (text, "a" * 64, intake.digest(text))
        entries = json.loads(fixtures.feed(14))["results"]
        state = {"document_states": {intake.digest(item["html_url"]): {
            "status": "manual_review", "attempts": 0, "active": True,
            "error": "document exceeds model input budget; manual review required",
            "item": {"title": item["title"], "summary": item["abstract"], "url": item["html_url"]},
            "target": fixtures.TARGET} for item in entries}}
        identities = set(state["document_states"])
        sw.save_store(state)
        self.fetch.return_value = fixtures.rollover_feed()
        for expected in (8, 2, 0):
            if expected:
                with self.assertRaisesRegex(RuntimeError, "incomplete"):
                    self.run_pass()
            else:
                self.run_pass()
            state = sw.load_store()
            self.assertEqual(set(state["document_states"]), identities)
            self.assertEqual(state["last_pass"]["pending_evaluations"], expected)
            self.assertLessEqual(state["last_pass"]["model_attempts"], 6)
            self.assertLessEqual(state["last_pass"]["documents_checked"], 120)
            if expected:
                self.assertNotIn("last_complete_run", state)
        self.assertEqual(len(sw.load_alerts()), 14)
        self.assertTrue(all(a["assessment_coverage"]["scope"] == "passages only" for a in sw.load_alerts()))
        self.assertEqual(self.model.call_count, 14)
        self.assertEqual(state["last_run_status"], "complete")

    def test_capture_failures_cannot_starve_a_retry(self):
        entries = json.loads(fixtures.feed(62))["results"]
        state = {"document_states": {intake.digest(item["html_url"]): {
            "status": "pending", "attempts": 1 if index == 61 else 0, "active": False,
            "checked_at": "2026-01-01T00:00:00+00:00",
            "item": {"title": item["title"], "summary": item["abstract"], "url": item["html_url"]},
            "target": fixtures.TARGET} for index, item in enumerate(entries)}}
        identities = set(state["document_states"])
        sw.save_store(state)
        self.fetch.return_value = fixtures.rollover_feed()
        def capture(url):
            if url.endswith("/61"):
                return fixtures.TEXT, "a" * 64, intake.digest(fixtures.TEXT)
            raise OSError("fixture unavailable")
        self.capture.side_effect = capture
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                self.run_pass()
        state = sw.load_store()
        self.assertEqual(set(state["document_states"]), identities)
        self.assertEqual(state["last_pass"]["pending_evaluations"], 61)
        self.assertEqual(state["document_states"][intake.digest(entries[-1]["html_url"])]["status"], "evaluated")
        self.assertEqual(self.model.call_count, 1)
        self.assertNotIn("last_complete_run", state)

    def test_deferred_checks_keep_an_assessed_inventory_incomplete(self):
        self.fetch.return_value = fixtures.feed(121)
        state = {}
        intake.collect_feeds(state, [fixtures.TARGET], self.fetch, sw.AI_KEYWORDS)
        for record in state["document_states"].values():
            record.update(status="evaluated", evaluated_text_sha256=intake.digest(fixtures.TEXT))
        sw.save_store(state)
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_pass()
        progress = sw.load_store()["last_pass"]
        self.assertEqual(progress["pending_evaluations"], 0)
        self.assertEqual(progress["documents_checked"], 120)
        self.assertEqual(progress["documents_deferred"], 1)
        self.assertEqual(len(sw.load_store()["document_states"]), 121)
        self.model.assert_not_called()

    def test_changed_deferred_document_does_not_keep_old_passage_ranges(self):
        self.run_pass()
        self.capture.return_value = (fixtures.TEXT + " Changed text.", "b" * 64,
                                     intake.digest(fixtures.TEXT + " Changed text."))
        with patch.object(sw, "MAX_MODEL_ATTEMPTS", 0), self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_pass()
        record = next(iter(sw.load_store()["document_states"].values()))
        self.assertEqual(record["status"], "pending")
        self.assertNotIn("assessment_coverage", record)

    def test_changed_capture_at_deadline_stays_pending_without_a_model_call(self):
        self.run_pass()
        changed = fixtures.TEXT + " A changed effective date."
        self.capture.return_value = (changed, "b" * 64, intake.digest(changed))
        self.model.reset_mock()
        with patch.object(sw.time, "monotonic", side_effect=[0, 0, sw.PASS_SECONDS + 1]):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                self.run_pass()
        state = sw.load_store()
        record = next(iter(state["document_states"].values()))
        self.assertEqual(record["status"], "pending")
        self.assertNotEqual(record["source_text_sha256"], record["evaluated_text_sha256"])
        self.assertEqual(state["last_pass"]["pending_evaluations"], 1)
        self.assertEqual(state["last_run_status"], "incomplete")
        self.model.assert_not_called()


class PassageTests(unittest.TestCase):
    def test_utf8_passages_fit_the_full_prompt_and_keep_offsets(self):
        text = ("Ordinary details. " * 1500 + "AI " + "資料" * 600 + " more details. ") * 12
        calls = []
        def model(prompt, **kwargs):
            calls.append(prompt)
            self.assertLessEqual(len(prompt.encode("utf-8")), sw.MODEL_INPUT_BYTES)
            selected = prompt.split("<source>", 1)[1].split("</source>", 1)[0]
            return dict(fixtures.RESULT, is_operator_duty_shift=False, duty_type="none",
                        priority_score=4, evidence_quote=selected.split(intake.PASSAGE_SEPARATOR)[0][:60])
        with patch.object(sw, "call_local_model", side_effect=model):
            result = sw.analyze_item_with_model("Notice", "", "Authority", "https://example.test/doc", source_text=text)
        self.assertEqual(len(calls), 1)
        coverage = result["assessment_coverage"]
        self.assertEqual(coverage["scope"], "passages only")
        self.assertGreater(len(coverage["ranges"]), 1)
        selected = intake.PASSAGE_SEPARATOR.join(text[a:b] for a, b in coverage["ranges"])
        self.assertIn("<source>" + selected + "</source>", calls[0])
        self.assertEqual(coverage["selected_text_sha256"], intake.digest(selected))

    def test_metadata_over_budget_never_calls_a_model(self):
        with patch.object(sw, "call_local_model") as model:
            result = sw.analyze_item_with_model("x" * sw.MODEL_INPUT_BYTES, "", "Authority", "https://example.test/doc", source_text=fixtures.TEXT)
        model.assert_not_called()
        self.assertEqual(result["evaluation_method"], "unassessed")
        self.assertIn("input budget too small", result["assessment_error"])

    def test_short_text_is_used_in_full(self):
        with patch.object(sw, "call_local_model", return_value=fixtures.RESULT):
            result = sw.analyze_item_with_model("Notice", "", "Authority", "https://example.test/doc", source_text=fixtures.TEXT)
        self.assertEqual(result["assessment_coverage"]["scope"], "extracted text")
        self.assertEqual(result["assessment_coverage"]["ranges"], [[0, len(fixtures.TEXT)]])

    def test_quote_cannot_cross_an_omitted_gap(self):
        text = fixtures.TEXT + " Ordinary background." * 1200 + fixtures.TEXT
        selected, ranges, _ = intake.select_passages(text, sw.AI_KEYWORDS, 12000)
        self.assertEqual(len(ranges), 2)
        forged = text[ranges[0][1] - 15:ranges[0][1]] + intake.PASSAGE_SEPARATOR + text[ranges[1][0]:ranges[1][0] + 15]
        self.assertIn(forged, selected)
        with patch.object(sw, "call_local_model", return_value=dict(fixtures.RESULT, evidence_quote=forged)):
            result = sw.analyze_item_with_model("Notice", "", "Authority", "https://example.test/doc", source_text=text)
        self.assertEqual(result["evaluation_method"], "unassessed")


class ConfigurationTests(unittest.TestCase):
    def test_only_ftc_declares_unavailable_coverage(self):
        limited = [t for t in sw.REGULATORY_TARGETS if t.get("failure_coverage")]
        self.assertEqual([t["id"] for t in limited], ["ftc_press_releases"])
        self.assertEqual(limited[0]["url"], "https://www.ftc.gov/feeds/press-release.xml")


if __name__ == "__main__":
    unittest.main()
