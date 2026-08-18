"""Regression tests for article publication dates used by the news-board intake."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import fetch_feeds
import fetch_vendor_news


class PublicationDateParsingTests(unittest.TestCase):
    def test_openai_date_before_heading(self):
        raw = """
        <div data-article-hero-copy-region="meta"><p>March 5, 2026</p></div>
        <h1>Introducing GPT-5.4</h1>
        """
        self.assertEqual(fetch_feeds.publication_date_from_html(raw), "2026-03-05")

    def test_anthropic_date_after_heading(self):
        raw = """
        <h1>Improving safeguards</h1><div class="body-3 agate">Aug 7, 2026</div>
        """
        self.assertEqual(fetch_feeds.publication_date_from_html(raw), "2026-08-07")

    def test_structured_publication_date_beats_nearby_date(self):
        raw = """
        <meta property="article:published_time" content="2026-07-31T09:15:00Z">
        <p>March 5, 2026</p><h1>Example</h1>
        """
        self.assertEqual(fetch_feeds.publication_date_from_html(raw), "2026-07-31")

    def test_month_name_url_date(self):
        url = "https://simonwillison.net/2026/Aug/7/openai-timeline/"
        self.assertEqual(fetch_feeds.publication_date_from_url(url), "2026-08-07")


class VendorFreshnessTests(unittest.TestCase):
    def test_sitemap_lastmod_does_not_become_publication_date(self):
        now = datetime.now(timezone.utc)
        current = (now - timedelta(days=1)).date()
        old = (now - timedelta(days=120)).date()
        sitemap_date = now.isoformat().replace("+00:00", "Z")
        current_human = current.strftime("%B %d, %Y").replace(" 0", " ")
        old_human = old.strftime("%B %d, %Y").replace(" 0", " ")
        old_url = "https://openai.com/index/old-post/"
        current_url = "https://openai.com/index/current-post/"
        sitemap = f"""
        <urlset>
          <url><loc>{old_url}</loc><lastmod>{sitemap_date}</lastmod></url>
          <url><loc>{current_url}</loc><lastmod>{sitemap_date}</lastmod></url>
        </urlset>
        """
        pages = {
            old_url: f"<title>Old post</title><p>{old_human}</p><h1>Old post</h1>",
            current_url: (f"<title>Current post</title><p>{current_human}</p>"
                          "<h1>Current post</h1>"),
        }

        with tempfile.TemporaryDirectory() as tmp:
            feed = Path(tmp, "feed_items.json")
            cache = Path(tmp, "vendor_titles.json")
            feed.write_text('{"items": []}', encoding="utf-8")

            def fake_get(url, timeout=25):
                return sitemap if url.endswith("sitemap.xml") else pages[url]

            patches = (
                mock.patch.object(fetch_vendor_news, "FEED", str(feed)),
                mock.patch.object(fetch_vendor_news, "TITLES", str(cache)),
                mock.patch.object(
                    fetch_vendor_news, "SITEMAPS",
                    [("OpenAI", "https://example.test/sitemap.xml", "/index/")]),
                mock.patch.object(fetch_vendor_news, "get", side_effect=fake_get),
                mock.patch.object(fetch_vendor_news.time, "sleep"),
                mock.patch.object(sys, "argv", ["fetch_vendor_news.py"]),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                fetch_vendor_news.main()

            items = json.loads(feed.read_text(encoding="utf-8"))["items"]
            self.assertEqual([item["headline"] for item in items], ["Current post"])
            self.assertEqual(items[0]["date"], current.isoformat())
            self.assertNotEqual(items[0]["date"], now.date().isoformat())

            cached = json.loads(cache.read_text(encoding="utf-8"))
            self.assertIn("publication dates", cached["_purpose"])
            self.assertEqual(cached[old_url]["published"], old.isoformat())

    def test_vendor_canonical_deduplication(self):
        existing_url = "https://openai.com/index/current-post/?utm_source=feed"
        sitemap_url = "https://openai.com/index/current-post/"
        now = datetime.now(timezone.utc)
        current = (now - timedelta(days=1)).date()
        sitemap_date = now.isoformat().replace("+00:00", "Z")
        current_human = current.strftime("%B %d, %Y").replace(" 0", " ")
        sitemap = f"""
        <urlset>
          <url><loc>{sitemap_url}</loc><lastmod>{sitemap_date}</lastmod></url>
        </urlset>
        """
        page = f"<title>Current post</title><p>{current_human}</p><h1>Current post</h1>"

        with tempfile.TemporaryDirectory() as tmp:
            feed = Path(tmp, "feed_items.json")
            cache = Path(tmp, "vendor_titles.json")
            feed.write_text(json.dumps({
                "items": [{
                    "headline": "Existing",
                    "sources": [{"url": existing_url}],
                }]
            }), encoding="utf-8")

            def fake_get(url, timeout=25):
                return sitemap if url.endswith("sitemap.xml") else page

            patches = (
                mock.patch.object(fetch_vendor_news, "FEED", str(feed)),
                mock.patch.object(fetch_vendor_news, "TITLES", str(cache)),
                mock.patch.object(
                    fetch_vendor_news, "SITEMAPS",
                    [("OpenAI", "https://example.test/sitemap.xml", "/index/")]),
                mock.patch.object(fetch_vendor_news, "get", side_effect=fake_get),
                mock.patch.object(fetch_vendor_news.time, "sleep"),
                mock.patch.object(sys, "argv", ["fetch_vendor_news.py"]),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
                fetch_vendor_news.main()

            items = json.loads(feed.read_text(encoding="utf-8"))["items"]
            self.assertEqual(len(items), 1)


class FeedDeduplicationTests(unittest.TestCase):
    def test_cross_feed_canonical_deduplication(self):
        feed_xml_1 = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item>
            <title>Direct Story</title>
            <link>https://techcrunch.com/2026/08/17/example-story/</link>
            <pubDate>Mon, 17 Aug 2026 12:00:00 +0000</pubDate>
          </item>
        </channel></rss>"""
        feed_xml_2 = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item>
            <title>Aggregated Story</title>
            <link>https://techcrunch.com/2026/08/17/example-story/?utm_source=hn</link>
            <pubDate>Mon, 17 Aug 2026 13:00:00 +0000</pubDate>
          </item>
        </channel></rss>"""

        with tempfile.TemporaryDirectory() as tmp:
            feed_path = Path(tmp, "feed_items.json")

            def fake_urlopen(req, timeout=20):
                url = req.full_url if hasattr(req, "full_url") else req
                content = feed_xml_1 if "feed1" in url else feed_xml_2
                m = mock.MagicMock()
                m.read.return_value = content.encode("utf-8")
                return m

            patches = (
                mock.patch.object(fetch_feeds, "OUT", str(feed_path)),
                mock.patch.object(fetch_feeds, "FEEDS", [
                    ("https://example.test/feed1.xml", False),
                    ("https://example.test/feed2.xml", False),
                ]),
                mock.patch.object(fetch_feeds.urllib.request, "urlopen", side_effect=fake_urlopen),
            )
            with patches[0], patches[1], patches[2]:
                fetch_feeds.main()

            items = json.loads(feed_path.read_text(encoding="utf-8"))["items"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["headline"], "Direct Story")


if __name__ == "__main__":
    unittest.main()
