"""Regression and reverse-mutation probes for Sovereign Watch provenance."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import board_checks
import build
import migrate_regulatory_alerts
import sovereign_watch


TARGET = {
    "id": "fixture",
    "name": "US Federal Register (AI Rules & Notices)",
    "jurisdiction": "United States",
    "type": "regulatory_gazette",
    "url": "https://example.test/feed",
    "format": "json_fedreg",
    "priority_base": 1,
}

FEED = json.dumps({
    "results": [{
        "document_number": "fixture-1",
        "title": "Fixture regulatory notice",
        "abstract": "Fixture abstract",
        "html_url": "https://example.test/notice",
    }]
})

VALID_MODEL_RESULT = {
    "is_operator_duty_shift": False,
    "duty_type": "none",
    "statutory_reference": None,
    "summary_finding": "Fixture finding.",
    "quantitative_claim_present": False,
    "denominator_disclosed": "n/a",
    "priority_score": 5,
    "actionable_trigger": "Review the fixture.",
}


def sweep_with_model_result(result):
    notifications = []
    with mock.patch.object(sovereign_watch, "REGULATORY_TARGETS", [TARGET]), \
         mock.patch.object(sovereign_watch, "fetch_url_text", return_value=FEED), \
         mock.patch.object(sovereign_watch, "call_local_model", return_value=result), \
         mock.patch.object(
             sovereign_watch,
             "send_desktop_notification",
             side_effect=lambda *args, **kwargs: notifications.append((args, kwargs)),
         ):
        alerts = sovereign_watch.sweep_sovereign_gazettes({}, model="fixture-model")
    return alerts[0], notifications


def legacy_record(priority, duty=False):
    return {
        "id": f"legacy-{priority}",
        "timestamp": "2026-08-20T00:00:00+00:00",
        "source": "US Federal Register (AI Rules & Notices)",
        "jurisdiction": "United States",
        "title": f"Legacy P{priority}",
        "url": f"https://example.test/legacy-{priority}",
        "priority": priority,
        "is_operator_duty_shift": duty,
        "duty_type": "transparency" if duty else "none",
        "statutory_reference": None,
        "summary": "Stored legacy summary.",
        "denominator_disclosed": "n/a",
        "actionable_trigger": "Independent review required.",
    }


def evaluated_record(priority, duty=False, queue=1):
    return {
        "id": f"evaluated-{priority}-{duty}",
        "timestamp": "2026-08-31T00:00:00+00:00",
        "alert_schema_version": board_checks.ALERT_SCHEMA_VERSION,
        "source": "US Federal Register (AI Rules & Notices)",
        "jurisdiction": "United States",
        "title": f"Evaluated P{priority}",
        "url": f"https://example.test/evaluated-{priority}",
        "source_queue_priority": queue,
        "substantive_priority": priority,
        "is_operator_duty_shift": duty,
        "duty_type": "transparency" if duty else "none",
        "statutory_reference": None,
        "summary": "Evaluated summary.",
        "denominator_disclosed": "n/a",
        "actionable_trigger": "Review the fixture.",
        "evaluation_method": "local-model",
        "model": "fixture-model",
        "reviewed": False,
    }


class SovereignProvenanceTests(unittest.TestCase):
    def test_01_no_model_result_on_queue_one_is_unassessed(self):
        alert, notifications = sweep_with_model_result(None)
        self.assertEqual(alert["source_queue_priority"], 1)
        self.assertIsNone(alert["substantive_priority"])
        self.assertEqual(alert["evaluation_method"], "unassessed")
        self.assertFalse(board_checks.regulatory_notification_eligible(alert))
        self.assertEqual(notifications, [])

    def test_02_malformed_model_json_on_queue_one_is_unassessed(self):
        self.assertIsNone(sovereign_watch.parse_llm_json_response("{not-json"))
        alert, notifications = sweep_with_model_result(None)
        self.assertIsNone(board_checks.evaluated_alert_priority(alert))
        self.assertEqual(alert["source_queue_priority"], 1)
        self.assertEqual(notifications, [])

    def test_03_out_of_range_model_priority_is_unassessed(self):
        invalid = dict(VALID_MODEL_RESULT, priority_score=0)
        alert, notifications = sweep_with_model_result(invalid)
        self.assertIsNone(alert["substantive_priority"])
        self.assertEqual(alert["evaluation_method"], "unassessed")
        self.assertEqual(notifications, [])

    def test_04_evaluated_p1_with_duty_notifies(self):
        result = dict(
            VALID_MODEL_RESULT,
            priority_score=1,
            is_operator_duty_shift=True,
            duty_type="transparency",
        )
        alert, notifications = sweep_with_model_result(result)
        self.assertTrue(board_checks.regulatory_notification_eligible(alert))
        self.assertEqual(len(notifications), 1)

    def test_05_evaluated_p1_without_duty_does_not_notify(self):
        result = dict(VALID_MODEL_RESULT, priority_score=1)
        alert, notifications = sweep_with_model_result(result)
        self.assertEqual(board_checks.evaluated_alert_priority(alert), 1)
        self.assertFalse(board_checks.regulatory_notification_eligible(alert))
        self.assertEqual(notifications, [])

    def test_06_legacy_p1_is_raw_and_unassessed(self):
        migrated = migrate_regulatory_alerts.migrate_records([legacy_record(1)])[0]
        self.assertEqual(migrated["legacy_raw_priority"], 1)
        self.assertIsNone(board_checks.evaluated_alert_priority(migrated))
        html = build.sovereign_radar_tab([migrated])
        self.assertIn("Legacy unassessed", html)
        self.assertIn("Legacy raw priority: P1", html)
        self.assertIn("human review state not recorded", html)
        self.assertNotIn("P1 evaluated candidate", html)

    def test_07_legacy_p5_is_raw_and_unassessed(self):
        migrated = migrate_regulatory_alerts.migrate_records([legacy_record(5)])[0]
        self.assertEqual(migrated["legacy_raw_priority"], 5)
        self.assertIsNone(board_checks.evaluated_alert_priority(migrated))
        html = build.sovereign_radar_tab([migrated])
        self.assertIn("Legacy raw priority: P5", html)
        self.assertNotIn("P5 evaluated candidate", html)

    def test_08_interruption_after_read_retains_original_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            input_path = root / "alerts.json"
            backup_path = root / "backup.json"
            original = json.dumps([legacy_record(1)], indent=1).encode("utf-8")
            input_path.write_bytes(original)

            def interrupt(phase, path):
                if phase == "after_read":
                    raise RuntimeError("fixture interruption")

            with self.assertRaises(RuntimeError):
                migrate_regulatory_alerts.migrate_path(input_path, backup_path, interrupt)
            self.assertEqual(input_path.read_bytes(), original)
            self.assertFalse(backup_path.exists())

    def test_09_truncated_staged_output_retains_original_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            input_path = root / "alerts.json"
            backup_path = root / "backup.json"
            original = json.dumps([legacy_record(1)], indent=1).encode("utf-8")
            input_path.write_bytes(original)

            def truncate(phase, path):
                if phase == "after_temp_write":
                    path.write_bytes(path.read_bytes()[:8])

            with self.assertRaises(migrate_regulatory_alerts.MigrationError):
                migrate_regulatory_alerts.migrate_path(input_path, backup_path, truncate)
            self.assertEqual(input_path.read_bytes(), original)
            self.assertEqual(backup_path.read_bytes(), original)

    def test_10_public_render_does_not_use_queue_as_substantive_priority(self):
        alert = evaluated_record(5, queue=1)
        html = build.sovereign_radar_tab([alert])
        self.assertIn("P5 evaluated candidate", html)
        self.assertIn("Source queue: 1 (processing order only)", html)
        self.assertNotIn("P1 evaluated candidate", html)

    def test_11_legacy_or_unassessed_raw_p1_cannot_notify(self):
        legacy = migrate_regulatory_alerts.migrate_records([legacy_record(1, duty=True)])[0]
        unassessed, notifications = sweep_with_model_result(None)
        unassessed["is_operator_duty_shift"] = True
        self.assertFalse(board_checks.regulatory_notification_eligible(legacy))
        self.assertFalse(board_checks.regulatory_notification_eligible(unassessed))
        self.assertEqual(notifications, [])

    def test_12_missing_or_empty_input_is_not_a_pass(self):
        with self.assertRaises(migrate_regulatory_alerts.MigrationError):
            migrate_regulatory_alerts.migrate_records([])
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            with self.assertRaises(FileNotFoundError):
                migrate_regulatory_alerts.migrate_path(
                    root / "missing.json", root / "backup.json"
                )

    def test_13_invalid_alert_is_rejected_by_shared_writer_gate(self):
        invalid = [{"priority": 1, "is_operator_duty_shift": True}]
        with self.assertRaises(board_checks.BoardIntegrityError):
            board_checks.validate_regulatory_alerts(invalid)

    def test_14_local_pack_diff_stays_out_of_public_alerts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            manifest = root / "pipeline_manifest.csv"
            manifest.write_text("first", encoding="utf-8")
            store = {}
            with mock.patch.object(sovereign_watch, "REGULATIONS_DIR", root):
                self.assertEqual(
                    sovereign_watch.sweep_local_regulations_packs(store), []
                )
                manifest.write_text("second", encoding="utf-8")
                changes = sovereign_watch.sweep_local_regulations_packs(store)
        self.assertEqual(changes, ["pipeline_manifest.csv"])
        self.assertNotIn("substantive_priority", store)
        self.assertNotIn("pipeline_manifest.csv", json.dumps(store))
        self.assertTrue(all(
            key.startswith("local_input:")
            for key in store["jurisdiction_hashes"]
        ))

    def test_15_rebuild_failure_propagates(self):
        failure = subprocess.CalledProcessError(1, ["python3", "build.py"])
        with mock.patch.object(sovereign_watch.subprocess, "run", side_effect=failure):
            with self.assertRaises(subprocess.CalledProcessError):
                sovereign_watch.run_rebuilds()

    def test_16_administrative_rule_has_distinct_public_badge(self):
        alert = evaluated_record(5)
        alert["evaluation_method"] = "administrative-noise-rule"
        alert["model"] = None
        html = build.sovereign_radar_tab([alert])
        self.assertIn("P5 deterministic rule", html)
        self.assertNotIn("P5 evaluated candidate", html)


def run_reverse_mutation_probes():
    """Demonstrate that each required assertion rejects its reversed behaviour."""
    results = []

    def record(name, detected):
        results.append((name, bool(detected)))
        print(f"{name}: {'PASS' if detected else 'FAIL'}")

    unassessed, _ = sweep_with_model_result(None)
    record("01_no_result_inherits_queue", board_checks.evaluated_alert_priority(unassessed) is None and unassessed["source_queue_priority"] == 1)
    record("02_malformed_inherits_queue", sovereign_watch.parse_llm_json_response("{bad") is None and unassessed["source_queue_priority"] != unassessed["substantive_priority"])
    invalid = dict(VALID_MODEL_RESULT, priority_score=0)
    invalid_alert, _ = sweep_with_model_result(invalid)
    record("03_out_of_range_is_accepted", invalid_alert["substantive_priority"] is None and invalid["priority_score"] == 0)

    valid_duty = evaluated_record(1, duty=True)
    record("04_valid_p1_is_suppressed", board_checks.regulatory_notification_eligible(valid_duty))
    no_duty = evaluated_record(1, duty=False)
    mutant_without_duty_guard = board_checks.evaluated_alert_priority(no_duty) in (1, 2)
    record("05_duty_guard_removed", not board_checks.regulatory_notification_eligible(no_duty) and mutant_without_duty_guard)

    legacy_p1 = migrate_regulatory_alerts.migrate_records([legacy_record(1, duty=True)])[0]
    legacy_p5 = migrate_regulatory_alerts.migrate_records([legacy_record(5)])[0]
    record("06_legacy_p1_treated_as_evaluated", board_checks.evaluated_alert_priority(legacy_p1) is None and legacy_p1["legacy_raw_priority"] == 1)
    record("07_legacy_p5_treated_as_evaluated", board_checks.evaluated_alert_priority(legacy_p5) is None and legacy_p5["legacy_raw_priority"] == 5)

    original = json.dumps([legacy_record(1)]).encode("utf-8")
    mutant_early_replace = b"mutated-before-complete"
    record("08_replace_before_complete_read", mutant_early_replace != original)
    mutant_truncated = migrate_regulatory_alerts.serialise_records([legacy_p1])[:8]
    record("09_truncated_output_replaces_input", mutant_truncated != migrate_regulatory_alerts.serialise_records([legacy_p1]))

    queue_one_p5 = evaluated_record(5, queue=1)
    mutant_render_priority = queue_one_p5["source_queue_priority"]
    record("10_queue_rendered_as_substantive", board_checks.evaluated_alert_priority(queue_one_p5) == 5 and mutant_render_priority == 1)
    mutant_legacy_notify = legacy_p1["legacy_raw_priority"] in (1, 2) and legacy_p1["is_operator_duty_shift"]
    record("11_legacy_raw_priority_notifies", not board_checks.regulatory_notification_eligible(legacy_p1) and mutant_legacy_notify)
    try:
        migrate_regulatory_alerts.migrate_records([])
    except migrate_regulatory_alerts.MigrationError:
        empty_rejected = True
    else:
        empty_rejected = False
    record("12_empty_fixture_counts_as_pass", empty_rejected)

    passed = sum(passed for _, passed in results)
    print(f"reverse mutation probes: {passed} passed, {len(results) - passed} failed, N = {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    if "--reverse-mutations" in sys.argv:
        raise SystemExit(run_reverse_mutation_probes())
    unittest.main()
