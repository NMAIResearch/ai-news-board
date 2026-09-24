"""Ensure daily builds cannot make retained historical material appear current."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build


class FreshnessPresentationTests(unittest.TestCase):
    def test_daily_source_dates_are_not_replaced_by_build_or_register_dates(self):
        rendered = build.freshness(
            "2026-09-24 10:00 UTC", "2026-09-23 06:00 UTC",
            {"generated": "2026-09-22T12:00:00+00:00"},
            {"generated": "2026-07-28"},
            {"generated": "2026-09-21 07:00 UTC"},
        )
        for expected in ["2026-09-23T06:00:00Z", "2026-09-22T12:00:00Z",
                         "2026-09-21T07:00:00Z", "2026-09-24T10:00:00Z"]:
            self.assertIn(expected, rendered)
        self.assertNotIn("2026-07-28", rendered)
        self.assertNotIn("just now", rendered)

    def test_missing_and_malformed_dates_stay_unavailable(self):
        rendered = build.freshness("2026-09-24", "not a date", {}, {}, {})
        self.assertEqual(rendered.count("date unavailable"), 3)
        self.assertNotIn("not a date", rendered)

    def test_historical_date_is_explicit_and_dynamic(self):
        rendered = build.reference_notice("Registers", "2026-07-28")
        self.assertIn("historical snapshot", rendered)
        self.assertIn("2026-07-28T00:00:00Z|dateonly", rendered)
        self.assertIn("Not refreshed by the daily news pipeline", rendered)
        self.assertIn("current status is unverified", rendered)

    def test_missing_reference_date_does_not_inherit_today(self):
        for date in [None, "", "2026-02-30", '<script>alert(1)</script>']:
            rendered = build.reference_notice("<input>", date)
            self.assertIn("date unavailable", rendered)
            self.assertNotIn("data-ts=", rendered)
            self.assertNotIn("<script>", rendered)
            self.assertIn("&lt;input&gt;", rendered)

    def test_generated_page_separates_reference_material_from_daily_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "index.html"
            with patch.object(build, "OUT", str(output)), patch("sys.argv", ["build.py"]):
                with contextlib.redirect_stdout(io.StringIO()):
                    build.main()
            page = output.read_text()
        news = page.split('<div id="tab-news"', 1)[1].split('<div id="tab-radar"', 1)[0]
        reference = page.split('<div id="tab-reference"', 1)[1]
        self.assertNotIn("Deflation register", news)
        self.assertNotIn("pane-upcoming", news)
        self.assertIn("Deflation register", reference)
        self.assertIn("Upcoming &amp; Announced", reference)
        self.assertIn("Historical gauge readings", reference)
        self.assertNotIn("Live gauges", page)
        self.assertIn('data-target="tab-reference"', page)


if __name__ == "__main__":
    unittest.main()
