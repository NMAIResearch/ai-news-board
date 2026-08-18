"""Regression tests for search and market trend monitor."""

import os
import unittest
from trend_monitor import scan_market_anomalies, WATCH_TOPICS

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TrendMonitorTests(unittest.TestCase):
    def test_watch_topics_all_seven_domains(self):
        expected_domains = [
            "AI Labour Market & Employment",
            "Forward-Looking Architectures & Research Automation",
            "AI IPOs, Private Marks & Public Listings",
            "Consumer Sentiment & Dark Patterns",
            "Physical Buildout, Grid & Hardware Chokepoints",
            "Sovereign Regulation & Antitrust",
            "Macro & Market Volatility"
        ]
        for dom in expected_domains:
            self.assertIn(dom, WATCH_TOPICS, f"Missing expected domain: {dom}")
            self.assertIn("keywords", WATCH_TOPICS[dom])
            self.assertGreater(len(WATCH_TOPICS[dom]["keywords"]), 6)

    def test_scan_market_anomalies_symmetrical(self):
        res = scan_market_anomalies()
        self.assertNotIn("error", res)
        self.assertIn("breakouts", res)
        self.assertIn("surges", res)
        self.assertIn("critical_drops", res)
        self.assertIn("warning_drops", res)
        self.assertIn("macro_moves", res)

        for drop in res["critical_drops"]:
            self.assertIn("ticker", drop)
            self.assertIn("change_pct", drop)
            self.assertLessEqual(drop["change_pct"], -5.0)

        for surge in res["surges"]:
            self.assertIn("ticker", surge)
            self.assertIn("change_pct", surge)
            self.assertGreaterEqual(surge["change_pct"], 5.0)
