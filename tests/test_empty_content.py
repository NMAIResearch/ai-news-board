"""Prevent empty captures from being presented as assessed article evidence."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import article_evidence as evidence
import label_items as labels


class EmptyContentTests(unittest.TestCase):
    def test_empty_success_does_not_establish_absence_of_figures(self):
        value, reason, settled = labels.tier1_denominator(
            {"fetch": "ok", "n_chars": 0, "spans": []})
        self.assertIsNone(value)
        self.assertFalse(settled)
        self.assertIn("empty article text", reason)

    def run_labels(self, human=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            url = "https://example.test/empty"
            record = {"fetch": "ok", "n_chars": 0, "spans": [],
                      "content_hash": "empty-body", "evidence_hash": "empty-spans"}
            item = {"headline": "Empty capture", "sources": [{"url": url}],
                    "denominator_stated": "n/a", "evidence_method": "rule",
                    "label_schema_version": labels.LABEL_SCHEMA_VERSION,
                    "content_hash": "empty-body", "evidence_hash": "empty-spans",
                    "label_source": "human" if human else "machine", "reviewed": human}
            (root / "feed.json").write_text(json.dumps({"items": [item]}))
            (root / "spans.json").write_text(json.dumps({url: record}))
            (root / "article_text.json").write_text(json.dumps({url: {"text": "", "status": "ok"}}))
            with patch.object(labels, "HERE", directory), \
                    patch.object(labels, "FEED", str(root / "feed.json")), \
                    patch.object(labels, "SPANS", str(root / "spans.json")), \
                    patch.object(labels, "call", side_effect=AssertionError("Unexpected model call for empty article")) as model, \
                    patch("sys.argv", ["label_items.py"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                labels.main()
            model.assert_not_called()
            return item, json.loads((root / "feed.json").read_text())["items"][0]

    def test_matching_cached_empty_label_is_replaced_without_model(self):
        _, actual = self.run_labels()
        self.assertEqual(actual["denominator_stated"], "?")
        self.assertEqual(actual["evidence_method"], "unassessed")
        self.assertEqual(actual["evidence_coverage"], {"seen": 0, "total": 0})
        self.assertFalse(actual["reviewed"])
        self.assertIn("empty article text", actual["label_evidence"])

    def test_human_review_is_preserved(self):
        before, after = self.run_labels(human=True)
        self.assertEqual(after, before)

    def test_evidence_requires_readable_body_as_well_as_http_success(self):
        url = "https://example.test/article"
        items = [{"headline": "Example", "sources": [{"url": url, "source_tier": 3}]}]
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "evidence.json"
            for body, expected in (("", False), (" \n\t", False), ("Readable article.", True)):
                with self.subTest(body=body):
                    records = {evidence.FEED: {"items": items}, evidence.SPANS: {},
                               evidence.TEXTS: {url: {"status": "ok", "text": body}},
                               evidence.STAKES: {}}
                    with patch.object(evidence, "load", side_effect=lambda p, default=None: records[p]), \
                            patch.object(evidence, "OUT", str(out)):
                        actual = evidence.compute()
                    self.assertEqual(actual[url]["fetched"], expected)


if __name__ == "__main__":
    unittest.main()
