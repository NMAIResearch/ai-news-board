"""Regression tests for search and market trend monitor."""

import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import trend_monitor
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


class MarketPercentageTests(unittest.TestCase):
    def scan(self, payload):
        with tempfile.TemporaryDirectory() as temporary:
            market = Path(temporary) / "market.json"
            market.write_text(json.dumps(payload))
            with mock.patch.object(trend_monitor, "MARKET_FILE", market):
                return scan_market_anomalies()

    def test_unknown_equity_percentages_do_not_hide_valid_quotes(self):
        for unknown in ({"change_pct": None}, {}):
            with self.subTest(unknown=unknown):
                result = self.scan({
                    "equities": {"UNKNOWN": unknown,
                                 "VALID": {"change_pct": 6.0, "value": 106}},
                    "indices": {"VALID": {"change_pct": -4.0}},
                })
                self.assertEqual([row["ticker"] for row in result["surges"]], ["VALID"])
                self.assertEqual([row["symbol"] for row in result["macro_moves"]], ["VALID"])

    def test_unknown_index_percentages_do_not_hide_valid_quotes(self):
        for unknown in ({"change_pct": None}, {}):
            with self.subTest(unknown=unknown):
                result = self.scan({
                    "equities": {"VALID": {"change_pct": -6.0}},
                    "indices": {"UNKNOWN": unknown, "VALID": {"change_pct": 4.0}},
                })
                self.assertEqual([row["ticker"] for row in result["critical_drops"]], ["VALID"])
                self.assertEqual([row["symbol"] for row in result["macro_moves"]], ["VALID"])

    def test_numeric_thresholds_and_non_alerting_changes_are_preserved(self):
        result = self.scan({
            "equities": {
                "BREAKOUT": {"change_pct": 10.0},
                "SURGE": {"change_pct": 5.0},
                "CRITICAL": {"change_pct": -5.0},
                "WARNING": {"change_pct": -3.0},
                "FLAT": {"change_pct": 0.0},
                "SMALL": {"change_pct": 2.99},
            },
            "indices": {"UP": {"change_pct": 3.0},
                        "DOWN": {"change_pct": -3.0},
                        "FLAT": {"change_pct": 0.0}},
        })
        for bucket, ticker in (("breakouts", "BREAKOUT"), ("surges", "SURGE"),
                               ("critical_drops", "CRITICAL"), ("warning_drops", "WARNING")):
            self.assertEqual([row["ticker"] for row in result[bucket]], [ticker])
        self.assertEqual([row["symbol"] for row in result["macro_moves"]], ["UP", "DOWN"])

    def test_monitor_writes_other_streams_when_market_percentages_are_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            market, output = root / "market.json", root / "trend_alerts.json"
            market.write_text(json.dumps({
                "equities": {"UNKNOWN": {"change_pct": None}},
                "indices": {"UNKNOWN": {"change_pct": None}},
            }))
            search = [{"query": "Example search"}]
            targeted = [{"category": "Example category"}]
            with mock.patch.object(trend_monitor, "MARKET_FILE", market), \
                    mock.patch.object(trend_monitor, "DATA_DIR", root), \
                    mock.patch.object(trend_monitor, "TREND_OUT", output), \
                    mock.patch.object(trend_monitor, "scan_search_trends", return_value=search), \
                    mock.patch.object(trend_monitor, "fetch_targeted_domain_news", return_value=targeted):
                result = trend_monitor.run_monitor(write=True)
            self.assertEqual(json.loads(output.read_text()), result)
            self.assertEqual(result["search_trend_matches"], search)
            self.assertEqual(result["targeted_domain_signals"], targeted)
            for bucket in ("breakouts", "surges", "critical_drops", "warning_drops", "macro_moves"):
                self.assertEqual(result["market_signals"][bucket], [])
