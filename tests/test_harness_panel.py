"""Regression tests for the source-bound harness compatibility panel."""

import copy
import json
import pathlib
import unittest

import build
from board_checks import BoardIntegrityError, validate_harnesses


ROOT = pathlib.Path(__file__).resolve().parents[1]


class HarnessPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "harnesses.json").read_text(encoding="utf-8"))

    def test_current_registry_is_valid(self):
        self.assertEqual(validate_harnesses(self.data), 5)

    def test_missing_source_commit_fails_closed(self):
        changed = copy.deepcopy(self.data)
        changed["source"]["commit"] = "short"
        with self.assertRaises(BoardIntegrityError):
            validate_harnesses(changed)

    def test_source_url_must_be_pinned_to_commit(self):
        changed = copy.deepcopy(self.data)
        changed["source"]["url"] = "https://github.com/NMAIResearch/plag-in/blob/main/docs/VERIFICATION.md"
        with self.assertRaises(BoardIntegrityError):
            validate_harnesses(changed)

    def test_rank_must_follow_declared_status_order(self):
        changed = copy.deepcopy(self.data)
        changed["entries"][1]["rank"] = 1
        with self.assertRaises(BoardIntegrityError):
            validate_harnesses(changed)

    def test_panel_states_scope_and_evidence_boundary(self):
        rendered = build.harnesses_tab(self.data)
        self.assertIn("not a ranking of model quality", rendered)
        self.assertIn("No installed client completed", rendered)
        self.assertIn("Evidence at PLAG IN commit", rendered)
        self.assertIn("#1", rendered)
        self.assertIn("#4", rendered)

    def test_obsolete_executive_fallbacks_are_absent(self):
        source = (ROOT / "build.py").read_text(encoding="utf-8")
        self.assertNotIn('shock_text = "BIDU', source)
        self.assertNotIn('top_rel_model = rel_first.get', source)
        self.assertNotIn('radar-badge">20</span>', source)


if __name__ == "__main__":
    unittest.main()
