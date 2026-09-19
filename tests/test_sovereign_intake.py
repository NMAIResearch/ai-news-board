"""Regression coverage for source failures, coverage, persistence and evidence contracts."""

import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import board_checks
import build
import sovereign_intake as intake
import sovereign_watch as sw


TEXT = "This is the captured source document. Operators must provide a visible disclosure before deploying the covered AI service."
QUOTE = "Operators must provide a visible disclosure before deploying the covered AI service."
RESULT = {"is_operator_duty_shift": True, "duty_type": "transparency", "statutory_reference": None,
          "summary_finding": "A disclosure is required.", "quantitative_claim_present": False,
          "denominator_disclosed": "n/a", "priority_score": 1, "actionable_trigger": "Review the disclosure requirement.",
          "document_status": "binding", "ai_relevance": "relevant", "evidence_quote": QUOTE}
TARGET = {"id": "fixture", "name": "Fixture authority", "url": "https://example.test/feed",
          "format": "json_fedreg", "priority_base": 1, "jurisdiction": "Fixture"}


def feed(n=1, **extra):
    return json.dumps({"results": [{"title": f"AI notice {i}", "html_url": f"https://example.test/document/{i}",
                                    "abstract": "An AI notice", "document_number": str(i)} for i in range(n)], **extra})


class FeedTests(unittest.TestCase):
    def test_all_entries_queued_and_paginated(self):
        state = {}
        with patch.object(sw, "fetch_url_text", side_effect=[feed(11, next_page_url="https://example.test/page2"), feed(13)]):
            records = intake.collect_feeds(state, [TARGET], sw.fetch_url_text, sw.AI_KEYWORDS)
        self.assertEqual(len(records), 13)
        self.assertEqual(state["source_states"]["fixture"]["status"], "ok")

    def test_html_and_fetch_failure_never_mean_clean(self):
        for body in (None, "<html><body>Page not found</body></html>", "{bad"):
            state = {}
            intake.collect_feeds(state, [TARGET], lambda _: body, sw.AI_KEYWORDS)
            self.assertEqual(state["source_states"]["fixture"]["status"], "failed")
            self.assertNotIn("last_success", state["source_states"]["fixture"])

    def test_feed_limit_is_explicit(self):
        state = {}
        pages = [feed(1, next_page_url=f"https://example.test/page{i}") for i in range(6)]
        with patch.object(sw, "fetch_url_text", side_effect=pages):
            intake.collect_feeds(state, [TARGET], sw.fetch_url_text, sw.AI_KEYWORDS)
        self.assertEqual(state["source_states"]["fixture"]["status"], "limited")

    def test_cross_origin_pagination_rejected(self):
        with self.assertRaises(ValueError):
            intake.parse_feed(feed(next_page_url="https://elsewhere.test/page"), TARGET)

    def test_all_rss_entries_before_keyword_filter(self):
        raw = "<rss><channel>" + "".join(f"<item><title>AI item {i}</title><link>https://example.test/{i}</link></item>" for i in range(40)) + "</channel></rss>"
        state = {}
        intake.collect_feeds(state, [dict(TARGET, format="rss", filter_ai=True)], lambda _: raw, __import__('re').compile('AI'))
        self.assertEqual(len(state["document_states"]), 40)

    def test_private_urls_rejected(self):
        for url in ("https://127.0.0.1/x", "https://localhost/x", "http://example.test", "https://user:pass@example.test"):
            self.assertFalse(intake.public_url(url))

    def test_capture_refuses_to_replace_existing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.txt"
            intake.immutable_text(path, TEXT)
            intake.immutable_text(path, TEXT)
            with self.assertRaises(ValueError):
                intake.immutable_text(path, TEXT + "changed")
            self.assertEqual(path.read_text(), TEXT)

    def test_document_body_route_and_challenge(self):
        self.assertEqual(intake.source_document_url("https://www.federalregister.gov/documents/2026/09/09/2026-18293/title"),
                         "https://www.federalregister.gov/documents/full_text/html/2026/09/09/2026-18293.html")
        with self.assertRaises(ValueError):
            intake.document_text("<h1>Request Access</h1>" + "This response is an access challenge. " * 10)
        self.assertEqual(intake.document_text("<html><nav>noise</nav><main>" + TEXT + "</main></html>"), TEXT)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.packs = self.root / "packs"
        self.packs.mkdir()
        (self.packs / "pipeline_manifest.csv").write_text("path\n")
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {"DATA_DIR": self.data, "STORE_FILE": self.data / "store.json",
                            "ALERTS_FILE": self.data / "alerts.json", "ALERTS_LOG": self.data / "events.jsonl",
                            "ALERTS_DIR": self.root / "bulletins", "REGULATIONS_DIR": self.packs,
                            "REGULATORY_TARGETS": [TARGET]}.items():
            self.stack.enter_context(patch.object(sw, name, value))
        self.fetch = self.stack.enter_context(patch.object(sw, "fetch_url_text", return_value=feed()))
        self.capture = self.stack.enter_context(patch.object(sw, "capture_source", return_value=(TEXT, "a" * 64, intake.digest(TEXT))))
        self.model = self.stack.enter_context(patch.object(sw, "call_local_model", return_value=dict(RESULT)))
        self.notify = self.stack.enter_context(patch.object(sw, "send_desktop_notification"))
        self.notify.return_value = True
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def run_pass(self):
        return sw.run_surveillance_pass(model="fixture-model", trigger_rebuild=False)

    def test_success_is_idempotent_and_notifies_after_commit(self):
        def check_commit(*args, **kwargs):
            self.assertTrue(sw.STORE_FILE.exists())
            self.assertTrue(sw.ALERTS_FILE.exists())
            return True
        self.notify.side_effect = check_commit
        self.assertEqual(self.run_pass(), (1, 1))
        self.assertEqual(self.run_pass(), (0, 1))
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(sum(args[0].endswith("duty candidate") for args, _ in self.notify.call_args_list), 1)

    def test_failed_model_retries_and_replaces_unassessed(self):
        self.model.return_value = None
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_pass()
        self.assertEqual(sw.load_alerts()[0]["evaluation_method"], "unassessed")
        self.model.return_value = dict(RESULT)
        self.assertEqual(self.run_pass(), (1, 1))
        self.assertEqual(sw.load_alerts()[0]["evaluation_method"], "local-model")

    def test_timeout_reason_is_stored_and_retryable(self):
        self.model.side_effect = sw.ModelCallError("model timeout")
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_pass()
        alert = sw.load_alerts()[0]
        self.assertEqual(alert["assessment_error"], "model timeout")
        self.assertIsNone(alert["substantive_priority"])
        self.assertFalse(alert["reviewed"])
        self.assertEqual(sum(args[0].endswith("duty candidate") for args, _ in self.notify.call_args_list), 0)
        self.model.side_effect = None
        self.assertEqual(self.run_pass(), (1, 1))
        self.assertEqual(sw.load_alerts()[0]["evaluation_method"], "local-model")

    def test_manual_review_does_not_consume_model_attempt_allowance(self):
        self.fetch.return_value = feed(2)
        self.model.side_effect = [sw.ModelCallError('document exceeds model input budget; manual review required'), dict(RESULT)]
        with patch.object(sw, 'MAX_MODEL_ATTEMPTS', 1):
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                self.run_pass()
        state = sw.load_store()
        self.assertEqual(state['last_pass']['model_attempts'], 1)
        self.assertEqual(state['last_pass']['manual_review_required'], 1)
        self.assertEqual(state['last_pass']['pending_evaluations'], 1)
        self.assertEqual(sum(r['status'] == 'evaluated' for r in state['document_states'].values()), 1)

    def test_model_timeout_respects_remaining_pass_budget(self):
        with patch.object(sw.time, 'monotonic', side_effect=[0, 0, sw.PASS_SECONDS - 7]):
            self.run_pass()
        self.assertEqual(self.model.call_args.kwargs['timeout'], 7)

    def test_source_body_change_reassessed(self):
        self.run_pass()
        text = TEXT + " A later amendment changes the commencement date."
        self.capture.return_value = (text, "b" * 64, intake.digest(text))
        self.assertEqual(self.run_pass(), (1, 2))
        self.assertEqual(self.model.call_count, 2)

    def test_alert_write_failure_does_not_commit_seen_state(self):
        with patch.object(sw, "save_alerts", side_effect=OSError("fixture storage failure")):
            with self.assertRaises(OSError):
                self.run_pass()
        self.assertFalse(sw.STORE_FILE.exists())
        self.notify.assert_not_called()
        self.assertEqual(self.run_pass(), (1, 1))

    def test_state_write_failure_recovers_without_duplicate(self):
        with patch.object(sw, "save_store", side_effect=OSError("fixture state failure")):
            with self.assertRaises(OSError):
                self.run_pass()
        self.assertEqual(len(sw.load_alerts()), 1)
        self.notify.assert_not_called()
        self.assertEqual(self.run_pass(), (1, 1))
        self.assertEqual(sum(args[0].endswith("duty candidate") for args, _ in self.notify.call_args_list), 1)

    def test_notification_failure_remains_retryable_without_new_document(self):
        self.notify.return_value = False
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_pass()
        self.assertEqual(len(sw.load_store()["pending_notifications"]), 1)
        self.notify.return_value = True
        self.run_pass()
        self.assertEqual(sw.load_store()["pending_notifications"], [])
        self.assertEqual(len(sw.load_store()["notification_receipts"]), 1)

    def test_completed_off_feed_records_do_not_create_permanent_backlog(self):
        self.run_pass()
        self.fetch.return_value = feed(0)
        self.assertEqual(self.run_pass(), (0, 1))
        self.assertEqual(sw.load_store()["last_pass"]["documents_checked"], 0)

    def test_source_failure_persists_incomplete_health(self):
        self.fetch.side_effect = OSError("network unavailable")
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_pass()
        state = sw.load_store()
        self.assertEqual(state["last_run_status"], "incomplete")
        self.assertEqual(state["last_pass"]["unhealthy_sources"], ["fixture"])
        self.assertNotIn("last_complete_run", state)
        self.model.assert_not_called()

    def test_evaluation_budget_retains_every_record(self):
        self.fetch.return_value = feed(11)
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_pass()
        state = sw.load_store()
        self.assertEqual(len(state["document_states"]), 11)
        self.assertEqual(state["last_pass"]["pending_evaluations"], 5)
        self.assertEqual(self.run_pass()[1], 11)

    def test_retry_survives_record_leaving_feed(self):
        self.model.return_value = None
        with self.assertRaises(RuntimeError):
            self.run_pass()
        self.fetch.return_value = feed(0)
        self.model.return_value = dict(RESULT)
        self.assertEqual(self.run_pass(), (1, 1))

    def test_real_pack_names_and_removal(self):
        pack = self.packs / "test_monitor"
        pack.mkdir()
        for name in ("clause_map.csv", "source_register.csv"):
            (pack / name).write_text("original")
        state = {}
        self.assertEqual(sw.sweep_local_regulations_packs(state), [])
        (pack / "clause_map.csv").write_text("changed")
        self.assertEqual(sw.sweep_local_regulations_packs(state), ["test_monitor/clause_map.csv"])
        (pack / "source_register.csv").unlink()
        with self.assertRaises(FileNotFoundError):
            sw.sweep_local_regulations_packs(state)

    def test_proposal_quote_and_reference_guards(self):
        for changes in ({"document_status": "proposed"}, {"evidence_quote": "Invented supporting words that do not occur"},
                        {"statutory_reference": "Article 999"}, {"actionable_trigger": "Monitor FCC-26-XXX"},
                        {"ai_relevance": "not_relevant"}):
            with self.subTest(changes=changes):
                self.model.return_value = dict(RESULT, **changes)
                result = sw.analyze_item_with_model("title", "snippet", "source", "https://example.test", source_text=TEXT)
                self.assertEqual(result["evaluation_method"], "unassessed")
                self.assertFalse(result["is_operator_duty_shift"])

    def test_schema_gate_rejects_broken_source_contract(self):
        self.run_pass()
        alert = sw.load_alerts()[0]
        for changes in ({"document_status": "proposed"}, {"source_sha256": "invalid"}, {"evidence_quote": None}, {"substantive_priority": "1"}):
            with self.subTest(changes=changes), self.assertRaises(board_checks.BoardIntegrityError):
                board_checks.validate_regulatory_alerts([dict(alert, **changes)])

    def test_withdrawal_suppresses_priority_and_action(self):
        self.run_pass()
        alert = sw.load_alerts()[0]
        alert["assessment_withdrawal"] = {"date": "2026-09-15", "reason": "Source contradiction."}
        self.assertFalse(board_checks.regulatory_notification_eligible(alert))
        page = build.sovereign_radar_tab([alert], health=sw.load_store())
        self.assertIn("Assessment withdrawn", page)
        self.assertNotIn("Actionable trigger:", page)
        self.assertIn("Source contradiction.", page)

    def test_incomplete_health_visible(self):
        self.run_pass()
        state = sw.load_store()
        state["last_run_status"] = "incomplete"
        state["last_pass"]["unhealthy_sources"] = ["fixture"]
        page = build.sovereign_radar_tab(sw.load_alerts(), health=state)
        self.assertIn("status: incomplete", page)
        self.assertIn("Failed or limited sources: 1", page)

    def test_same_writer_lock_blocks_second_writer(self):
        path = self.root / "writer.lock"
        with intake.writer_lock(path):
            with self.assertRaisesRegex(RuntimeError, "another board writer"):
                with intake.writer_lock(path):
                    self.fail("second writer acquired lease")

    def test_malformed_state_is_not_silently_reset(self):
        sw.STORE_FILE.write_text('{bad')
        with self.assertRaises(json.JSONDecodeError):
            sw.load_store()


if __name__ == "__main__":
    unittest.main()
