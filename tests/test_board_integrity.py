"""Regression tests for board provenance, topic matching and semantic joins."""

import unittest

from apply_ratings import rate, source_identity
from article_evidence import claim_relative_tier
from board_checks import BoardIntegrityError, validate_board
from label_items import (LABEL_SCHEMA_VERSION, PROMPT_CHAR_BUDGET, current_machine_label,
                         item_block, tier1_denominator)
from extract_spans import (FURNITURE, TIME_FURNITURE, content_region,
                           drop_cross_article_duplicates, evidence_hash, evidence_text,
                           sentence_key)
from topic_matcher import load_registry, match_texts
from url_identity import canonical_url


class UrlIdentityTests(unittest.TestCase):
    def test_distinct_youtube_videos_do_not_collapse(self):
        first = canonical_url("https://www.youtube.com/watch?v=alpha&utm_source=x")
        second = canonical_url("https://youtu.be/beta?t=20")
        self.assertNotEqual(first, second)

    def test_same_youtube_video_normalises_to_one_identity(self):
        full = canonical_url("https://www.youtube.com/watch?v=alpha&t=20")
        short = canonical_url("https://youtu.be/alpha?si=tracking")
        self.assertEqual(full, short)

    def test_semantic_query_parameters_are_retained(self):
        first = canonical_url("https://example.test/view?id=1&utm_campaign=x")
        second = canonical_url("https://example.test/view?id=2&utm_campaign=x")
        self.assertNotEqual(first, second)

    def test_ambiguous_source_parameter_is_retained(self):
        first = canonical_url("https://example.test/view?source=one")
        second = canonical_url("https://example.test/view?source=two")
        self.assertNotEqual(first, second)


class RatingIdentityTests(unittest.TestCase):
    def setUp(self):
        self.sources = {"trusted": [("deepmind.google", "")],
                        "caution": [], "blocked": []}

    def test_article_path_does_not_inherit_subject_rating(self):
        item = {"sources": [{"name": "Trade Press",
                             "url": "https://press.example/deepmind-launch"}]}
        self.assertEqual(rate(source_identity(item), self.sources)[0], "ok")

    def test_publisher_hostname_can_match(self):
        item = {"sources": [{"name": "Google DeepMind",
                             "url": "https://deepmind.google/blog/example"}]}
        self.assertEqual(rate(source_identity(item), self.sources)[0], "trusted")


class TopicMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()

    def test_silicon_valley_is_not_a_chip_match(self):
        match = match_texts("Silicon Valley funding rises", [], [], self.registry)
        self.assertNotIn("chips", [item["topic"] for item in match["topics"]])

    def test_remote_code_execution_is_not_code_automation(self):
        spans = ["The AI assesses code for software engineers using coding agents."]
        match = match_texts("Remote code execution vulnerability fixed", [], spans,
                            self.registry)
        self.assertNotIn("code_automation", [item["topic"] for item in match["topics"]])

    def test_watering_can_is_not_a_water_topic(self):
        spans = ["The robot put the watering can on the shelf."]
        match = match_texts("Robotics demonstration", [], spans, self.registry)
        self.assertNotIn("water", [item["topic"] for item in match["topics"]])

    def test_specific_code_claim_can_anchor(self):
        match = match_texts("AI-written code reaches 80% of new code", [], [], self.registry)
        self.assertEqual(match["anchor"]["topic"], "code_automation")

    def test_repeated_weak_span_does_not_manufacture_topic(self):
        spans = ["The project costs one billion dollars."] * 10
        match = match_texts("Project update", [], spans, self.registry)
        self.assertNotIn("cost", [item["topic"] for item in match["topics"]])

    def test_tied_anchor_candidates_abstain(self):
        registry = {
            "a": {"label": "A", "topic_min_score": 1, "anchor_min_score": 2,
                  "rules": [{"phrase": "same", "score": 1}],
                  "anchors": [{"kind": "test", "label": "A", "url": "https://a"}]},
            "b": {"label": "B", "topic_min_score": 1, "anchor_min_score": 2,
                  "rules": [{"phrase": "same", "score": 1}],
                  "anchors": [{"kind": "test", "label": "B", "url": "https://b"}]},
        }
        match = match_texts("same", [], [], registry)
        self.assertIsNone(match["anchor"])
        self.assertTrue(match["ambiguous"])

    def test_article_only_match_does_not_create_topic_or_anchor(self):
        spans = ["Gemini 3.6 benchmark results were discussed."]
        match = match_texts("Data systems for agents", [], spans, self.registry)
        self.assertNotIn("models", [item["topic"] for item in match["topics"]])
        self.assertIsNone(match["anchor"])


class FigureLabelTests(unittest.TestCase):
    def test_machine_label_is_invalidated_by_article_change(self):
        item = {"label_schema_version": LABEL_SCHEMA_VERSION,
                "evidence_method": "local-model", "content_hash": "old",
                "evidence_hash": "old-evidence"}
        self.assertFalse(current_machine_label(
            item, {"content_hash": "new", "evidence_hash": "new-evidence"}))

    def test_matching_schema_and_content_hash_can_carry(self):
        item = {"label_schema_version": LABEL_SCHEMA_VERSION,
                "evidence_method": "rule", "content_hash": "same",
                "evidence_hash": "same-evidence"}
        self.assertTrue(current_machine_label(
            item, {"content_hash": "same", "evidence_hash": "same-evidence"}))

    def test_machine_label_is_invalidated_by_extraction_change(self):
        old = evidence_hash("same-body", [{"sentence": "$4bn"}])
        new = evidence_hash("same-body", [])
        self.assertNotEqual(old, new)

    def test_no_spans_is_na(self):
        rec = {"fetch": "ok", "n_chars": 200, "spans": []}
        self.assertEqual(tier1_denominator(rec),
                         ("n/a", "no figure in 200 chars of article text", True))

    def test_incomplete_rules_escalate_complete_set(self):
        rec = {"fetch": "ok", "n_chars": 200, "spans": [
            {"sentence": "40% of 100 users", "base_cue": True},
            {"sentence": "$4 billion", "base_cue": False},
        ]}
        value, _, settled = tier1_denominator(rec)
        self.assertIsNone(value)
        self.assertFalse(settled)
        block = item_block(1, {"headline": "Example"}, rec, "Opening")
        self.assertIn("40% of 100 users", block)
        self.assertIn("$4 billion", block)

    def test_figure_sentences_are_not_truncated(self):
        sentence = "x" * 400
        rec = {"spans": [{"sentence": sentence}]}
        self.assertIn(sentence, item_block(1, {"headline": "Example"}, rec, ""))

    def test_prompt_budget_has_context_margin(self):
        self.assertLess(PROMPT_CHAR_BUDGET, 80_000)
        self.assertGreater(PROMPT_CHAR_BUDGET, 60_000)

    def test_article_element_beats_outer_main(self):
        raw = "<main><article>" + ("evidence " * 80) + "</article>related $9bn</main>"
        region, scope = content_region(raw)
        self.assertEqual(scope, "article")
        self.assertNotIn("related $9bn", region)

    def test_legacy_techcrunch_related_rail_is_trimmed(self):
        text = ("Article evidence " * 40) + "\nRelated\nOther story costs $9bn"
        clean = evidence_text(text, "https://techcrunch.com/story")
        self.assertNotIn("Other story", clean)

    def test_comment_tail_is_trimmed(self):
        text = ("Article evidence " * 40) + "\n15 Comments\nReader says it cost $9bn"
        clean = evidence_text(text, "https://example.test/story")
        self.assertNotIn("Reader says", clean)

    def test_duplicate_sentence_key_ignores_spacing_and_case(self):
        self.assertEqual(sentence_key("A  $4bn Figure"), sentence_key("a $4bn figure"))

    def test_cross_article_duplicate_span_is_removed(self):
        records = {
            "a": {"spans": [{"sentence": "Recommended item costs $4bn"}]},
            "b": {"spans": [{"sentence": "Recommended item costs $4bn"}]},
        }
        self.assertEqual(drop_cross_article_duplicates(records), 2)
        self.assertEqual(records["a"]["spans"], [])
        self.assertEqual(records["b"]["spans"], [])

    def test_author_biography_number_is_furniture(self):
        self.assertIsNotNone(FURNITURE.search(
            "She has covered the tech industry for over 18 years."))

    def test_document_metadata_is_furniture(self):
        samples = [
            "DOI: 10.1109/MSEC.2026.3678214",
            "Aug 6th 2026 | 8 min read",
            "See all comments (16)",
            "Figure 1: CUDA-to-MLX optimisation translation map.",
            "Algorithm 1: K-Search via co-evolving world models.",
        ]
        for sentence in samples:
            with self.subTest(sentence=sentence):
                self.assertIsNotNone(FURNITURE.search(sentence))

    def test_substantive_figure_caption_is_retained(self):
        sentence = "Figure 1: Accuracy rose by 20%."
        self.assertIsNone(FURNITURE.search(sentence))

    def test_publisher_datelines_are_furniture(self):
        samples = [
            "12:41 PM PDT · August 8, 2026",
            "Aug 8, 2026, 5:53 PM UTC",
            ("Posted Mon 10 Aug 2026 at 4:44am Mon 10 Aug 2026 at 4:44am, "
             "updated Mon 10 Aug 2026 at 8:36am"),
        ]
        for sentence in samples:
            with self.subTest(sentence=sentence):
                self.assertIsNotNone(TIME_FURNITURE.fullmatch(sentence))

    def test_embedded_video_duration_is_furniture(self):
        self.assertIsNotNone(TIME_FURNITURE.fullmatch("VIDEO 3:11 03:11"))

    def test_substantive_time_sentence_is_retained(self):
        sentence = "The service recovered at 3:11 PM after 42 minutes."
        self.assertIsNone(TIME_FURNITURE.fullmatch(sentence))


class ClaimTierTests(unittest.TestCase):
    def test_unknown_publisher_relationship_has_no_claim_tier(self):
        item = {"sources": [{"url": "https://press.example/story"}]}
        tier, relationship, _ = claim_relative_tier(item, "OpenAI", {"publisher_owner": {}})
        self.assertIsNone(tier)
        self.assertEqual(relationship, "unresolved")

    def test_subject_publisher_resolves_claim_tier(self):
        item = {"sources": [{"url": "https://openai.com/index/example"}]}
        stakes = {"publisher_owner": {"openai.com": "OpenAI"}, "stakes": {}}
        tier, relationship, _ = claim_relative_tier(item, "OpenAI", stakes)
        self.assertEqual(tier, 5)
        self.assertEqual(relationship, "publisher-is-subject")


class IntegrityGateTests(unittest.TestCase):
    def test_n_a_with_spans_fails(self):
        item = {
            "headline": "Example", "denominator_stated": "n/a",
            "evidence_method": "local-model",
            "evidence_coverage": {"seen": 1, "total": 1}, "content_hash": "h",
            "topics": [],
            "sources": [{"name": "Press", "url": "https://press.example/a",
                         "source_type": "trade-press", "source_tier": 3}],
        }
        spans = {"https://press.example/a": {"fetch": "ok", "content_hash": "h",
                                               "spans": [{"sentence": "50%"}]}}
        with self.assertRaises(BoardIntegrityError):
            validate_board([item], spans, {}, {},
                           {"trade-press": {"tier": 3}})

    def test_numeric_claim_tier_requires_relationship(self):
        item = {
            "headline": "Example", "denominator_stated": "?", "topics": [],
            "sources": [{"name": "Press", "url": "https://press.example/a",
                         "source_type": "trade-press", "source_tier": 3}],
        }
        evidence = {"https://press.example/a": {"source_tier": 3, "claim_tier": 4,
                                                  "claim_relationship": "unresolved"}}
        with self.assertRaises(BoardIntegrityError):
            validate_board([item], {}, evidence, {},
                           {"trade-press": {"tier": 3}})

    def test_machine_label_requires_both_hashes(self):
        item = {
            "headline": "Example",
            "denominator_stated": "N",
            "evidence_method": "local-model",
            "evidence_coverage": {"seen": 1, "total": 1},
            "sources": [{"url": "https://example.test/story",
                         "source_type": "press", "source_tier": 3}],
        }
        spans = {"https://example.test/story": {
            "fetch": "ok", "spans": [{"sentence": "$4bn"}],
            "content_hash": "", "evidence_hash": "",
        }}
        source_types = {"press": {"tier": 3}}
        with self.assertRaises(BoardIntegrityError):
            validate_board([item], spans, {}, {}, source_types)


if __name__ == "__main__":
    unittest.main()
