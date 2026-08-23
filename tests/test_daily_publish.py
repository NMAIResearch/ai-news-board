import datetime as dt
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

import daily_publish
import sovereign_watch


class DailyPublishTests(unittest.TestCase):
    def test_git_preserves_leading_porcelain_status_space(self):
        result = subprocess.CompletedProcess(
            args=["git", "status"], returncode=0, stdout=" M PIPELINE.md\n", stderr=None
        )
        with mock.patch.object(daily_publish, "run", return_value=result):
            self.assertEqual(daily_publish.git("status"), " M PIPELINE.md")

    def test_status_paths_extracts_modified_and_untracked(self):
        raw = " M data/market.json\n?? alerts/sovereign_bulletin_2026-08-23.md\n"
        self.assertEqual(
            daily_publish.status_paths(raw),
            ["data/market.json", "alerts/sovereign_bulletin_2026-08-23.md"],
        )

    def test_status_paths_rejects_rename(self):
        with self.assertRaises(daily_publish.PublishError):
            daily_publish.status_paths("R  old.json -> new.json\n")

    def test_publish_allowlist_accepts_generated_outputs(self):
        paths = ["data/market.json", "feed_items.json", "index.html"]
        self.assertEqual(
            daily_publish.require_allowed(paths, daily_publish.PUBLISH_PATTERNS, "test"),
            paths,
        )

    def test_publish_allowlist_rejects_code(self):
        with self.assertRaises(daily_publish.PublishError):
            daily_publish.require_allowed(
                ["build.py"], daily_publish.PUBLISH_PATTERNS, "test"
            )

    def test_require_today_rejects_old_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            target = root / "index.html"
            target.write_text("x", encoding="utf-8")
            with mock.patch.object(daily_publish, "REPO", root):
                with self.assertRaises(daily_publish.PublishError):
                    daily_publish.require_today(
                        ["index.html"], today=dt.date(2099, 1, 1)
                    )

    def test_sovereign_model_failure_is_unassessed(self):
        with mock.patch.object(sovereign_watch, "call_local_model", return_value=None):
            result = sovereign_watch.analyze_item_with_model(
                "A regulation title", "A duty and an article are mentioned.", "Test source", "https://example.test"
            )
        self.assertEqual(result["evaluation_method"], "unassessed")
        self.assertEqual(result["priority_score"], 5)
        self.assertFalse(result["is_operator_duty_shift"])
        self.assertFalse(result["reviewed"])

    def test_sovereign_model_schema_rejects_out_of_range_priority(self):
        value = {
            "is_operator_duty_shift": True,
            "duty_type": "transparency",
            "statutory_reference": "Article 1",
            "summary_finding": "A bounded finding.",
            "quantitative_claim_present": False,
            "denominator_disclosed": "n/a",
            "priority_score": 0,
            "actionable_trigger": "Review the primary.",
        }
        self.assertIsNone(sovereign_watch.validate_model_analysis(value, "test-model"))


if __name__ == "__main__":
    unittest.main()
