"""Regression tests for the per-feed cap ordering.

The cap is positional and feed order is recency order, so before `prioritise` existed a
publisher posting more than `per_feed` items a day silently lost everything below the top of
the file. On 2026-08-27 that dropped the Nvidia and Hugging Face acquisition report while a
novelty item from the same publisher survived.
"""

import unittest

import fetch_feeds


def row(title):
    return (title, f"https://example.test/{abs(hash(title))}", "Thu, 27 Aug 2026")


class FeedPriorityTests(unittest.TestCase):
    def test_the_2026_08_27_regression(self):
        """The acquisition survives a cap of six that previously excluded it."""
        newer_filler = [
            row("Hugging Face is selling a cute $399 open source duck robot, Microduck"),
            row("Google's AI Mode can now track flight prices, help book hotels, and more"),
            row("Gemini Omni 1.1 Flash lets you build with more control"),
            row("Plaud's new earphones come with an eSIM-enabled case"),
            row("AI helps design new materials that work in the real world"),
            row("Serve Markdown to AI Agents with Accept Headers"),
        ]
        acquisition = row("Nvidia closes in on Hugging Face acquisition")
        rows = newer_filler + [acquisition]

        self.assertNotIn(acquisition, rows[:6], "precondition: the bug needs it below the cap")
        self.assertIn(acquisition, fetch_feeds.prioritise(rows)[:6])

    def test_relative_order_is_stable_within_each_group(self):
        first = row("Regulator fines a vendor")
        second = row("Rival sues a vendor")
        filler_a = row("A model gets a new feature")
        filler_b = row("Another model gets a new feature")
        out = fetch_feeds.prioritise([filler_a, first, filler_b, second])
        self.assertEqual(out, [first, second, filler_a, filler_b])

    def test_nothing_is_dropped(self):
        rows = [row("A breach was disclosed"), row("A product shipped")]
        self.assertCountEqual(fetch_feeds.prioritise(rows), rows)
        self.assertEqual(len(fetch_feeds.prioritise(rows)), len(rows))

    def test_ordinary_headlines_do_not_match(self):
        for title in [
            "Google announces Gemini 3.5 Transcribe for AI-powered speech-to-text",
            "AI helps design new materials that work in the real world",
            "Putting sign language AI into users' hands",
        ]:
            self.assertIsNone(fetch_feeds.PRIORITY_TERMS.search(title), title)

    def test_material_events_match(self):
        for title in [
            "Nvidia closes in on Hugging Face acquisition",
            "OpenAI subpoenaed by Alabama AG over Hugging Face hack",
            "Anthropic raises $65 billion at a $965 billion valuation",
            "Regulator bans a deployment",
            "Vendor discontinues a model family",
        ]:
            self.assertIsNotNone(fetch_feeds.PRIORITY_TERMS.search(title), title)

    def test_empty_and_missing_titles_are_safe(self):
        rows = [(None, "https://example.test/a", ""), ("", "https://example.test/b", "")]
        self.assertEqual(fetch_feeds.prioritise(rows), rows)


if __name__ == "__main__":
    unittest.main()
