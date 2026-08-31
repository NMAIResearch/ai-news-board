import pathlib
import unittest

import build


ROOT = pathlib.Path(__file__).resolve().parents[1]


def item(article_url, headline):
    return {
        "headline": headline,
        "sources": [{"url": article_url}],
    }


class PrimarySourcesPanelTests(unittest.TestCase):
    def test_uses_fetched_article_evidence_and_preserves_origin(self):
        article_url = "https://news.example.test/story"
        rows = build.article_primary_sources(
            [item(article_url, "Feed headline")],
            {
                article_url: {
                    "fetched": True,
                    "headline": "Evidence headline",
                    "primary_link_examples": ["https://arxiv.org/abs/2608.00001"],
                }
            },
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["article_url"], article_url)
        self.assertEqual(rows[0]["article_headline"], "Evidence headline")
        self.assertEqual(rows[0]["label"], "arXiv 2608.00001")

    def test_deduplicates_canonical_primary_urls(self):
        first = "https://news.example.test/one"
        second = "https://news.example.test/two"
        rows = build.article_primary_sources(
            [item(first, "One"), item(second, "Two")],
            {
                first: {
                    "fetched": True,
                    "primary_link_examples": [
                        "https://example.gov/record?id=7&utm_source=news"
                    ],
                },
                second: {
                    "fetched": True,
                    "primary_link_examples": ["https://example.gov/record?id=7"],
                },
            },
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["article_headline"], "One")

    def test_skips_unfetched_and_non_web_records(self):
        unfetched = "https://news.example.test/unfetched"
        fetched = "https://news.example.test/fetched"
        rows = build.article_primary_sources(
            [item(unfetched, "Unfetched"), item(fetched, "Fetched")],
            {
                unfetched: {
                    "fetched": False,
                    "primary_link_examples": ["https://example.gov/should-not-render"],
                },
                fetched: {
                    "fetched": True,
                    "primary_link_examples": [
                        "file:///tmp/local.pdf",
                        "https://doi.org/10.1000/example",
                    ],
                },
            },
        )
        self.assertEqual([row["url"] for row in rows], ["https://doi.org/10.1000/example"])

    def test_limit_is_enforced(self):
        article_url = "https://news.example.test/story"
        rows = build.article_primary_sources(
            [item(article_url, "Story")],
            {
                article_url: {
                    "fetched": True,
                    "primary_link_examples": [
                        "https://example.gov/one",
                        "https://example.gov/two",
                    ],
                }
            },
            limit=1,
        )
        self.assertEqual(len(rows), 1)

    def test_retired_scholar_payload_is_not_a_live_dependency(self):
        for relative in ("build.py", "refresh.sh", "daily_publish.py", "README.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertNotIn("fetch_scholar.py", text)
                self.assertNotIn("scholar_items.json", text)


if __name__ == "__main__":
    unittest.main()
