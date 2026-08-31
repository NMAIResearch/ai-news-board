"""Regression tests for the source-separated harness landscape."""

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
        self.assertEqual(validate_harnesses(self.data), 4)

    def test_duplicate_public_source_fails_closed(self):
        changed = copy.deepcopy(self.data)
        changed["sources"][1]["id"] = changed["sources"][0]["id"]
        with self.assertRaises(BoardIntegrityError):
            validate_harnesses(changed)

    def test_public_source_requires_its_evidence_boundary(self):
        changed = copy.deepcopy(self.data)
        changed["sources"][0]["boundary"] = ""
        with self.assertRaises(BoardIntegrityError):
            validate_harnesses(changed)

    def test_board_authored_rank_fails_closed(self):
        changed = copy.deepcopy(self.data)
        changed["sources"][0]["rank"] = 1
        with self.assertRaises(BoardIntegrityError):
            validate_harnesses(changed)

    def test_project_snapshot_url_must_be_pinned_to_commit(self):
        changed = copy.deepcopy(self.data)
        changed["project_status"]["source"]["url"] = (
            "https://github.com/NMAIResearch/plag-in/blob/main/docs/VERIFICATION.md"
        )
        with self.assertRaises(BoardIntegrityError):
            validate_harnesses(changed)

    def test_panel_states_scope_and_evidence_boundary(self):
        rendered = build.harnesses_tab(self.data)
        self.assertIn("No composite rank", rendered)
        self.assertIn("OpenLabor Harness Ranking", rendered)
        self.assertIn("HarnessMatch", rendered)
        self.assertIn("Best of Agent Harnesses", rendered)
        self.assertIn("HarnessRank", rendered)
        self.assertIn("PLAG IN prototype compatibility snapshot", rendered)
        self.assertNotIn(">#1</span>", rendered)

    def test_required_method_references_are_rendered(self):
        rendered = build.harnesses_tab(self.data)
        self.assertIn("Qihoo360 Harness-Bench", rendered)
        self.assertIn("Harbor", rendered)
        self.assertIn("not a ranking authority", rendered)

    def test_obsolete_executive_fallbacks_are_absent(self):
        source = (ROOT / "build.py").read_text(encoding="utf-8")
        self.assertNotIn('shock_text = "BIDU', source)
        self.assertNotIn('top_rel_model = rel_first.get', source)
        self.assertNotIn('radar-badge">20</span>', source)


if __name__ == "__main__":
    unittest.main()
