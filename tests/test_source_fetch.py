"""Verify bounded source fetching and source-specific transport compatibility."""

import urllib.error
import unittest
from unittest.mock import patch

import sovereign_watch as sw


class Response:
    def __init__(self, data):
        self.data = data
        self.closed = False

    def read(self, limit):
        return self.data[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


class SourceFetchTests(unittest.TestCase):
    def test_ftc_compatible_header_and_closed_response(self):
        reply = Response(b"<rss><channel/></rss>")
        with patch.object(sw.urllib.request, "urlopen", return_value=reply) as fetch:
            result = sw.fetch_url_text("https://www.ftc.gov/feeds/press-release.xml")
        request = fetch.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), "Mozilla/5.0")
        self.assertEqual(request.full_url, "https://www.ftc.gov/feeds/press-release.xml")
        self.assertEqual(result, "<rss><channel/></rss>")
        self.assertTrue(reply.closed)

    def test_other_host_keeps_declared_identity(self):
        with patch.object(sw.urllib.request, "urlopen", return_value=Response(b"source")) as fetch:
            sw.fetch_url_text("https://www.ftc.gov.other.example/record")
        self.assertEqual(fetch.call_args.args[0].get_header("User-agent"), sw.USER_AGENT)

    def test_nonpublic_or_credentialed_url_refused_before_fetch(self):
        urls = ["http://www.ftc.gov/record", "https://127.0.0.1/record",
                "https://www.ftc.gov@other.example/record"]
        for url in urls:
            with self.subTest(url=url), patch.object(sw.urllib.request, "urlopen") as fetch:
                with self.assertRaises(ValueError):
                    sw.fetch_url_text(url)
                fetch.assert_not_called()

    def test_oversize_response_refused_and_closed(self):
        reply = Response(b"x" * 5)
        with patch.object(sw.intake, "MAX_SOURCE_BYTES", 4), \
             patch.object(sw.urllib.request, "urlopen", return_value=reply):
            with self.assertRaisesRegex(ValueError, "byte limit"):
                sw.fetch_url_text("https://www.ftc.gov/record")
        self.assertTrue(reply.closed)

    def test_http_refusal_propagates(self):
        error = urllib.error.HTTPError("https://www.ftc.gov/record", 403, "refused", {}, None)
        self.addCleanup(error.close)
        with patch.object(sw.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                sw.fetch_url_text("https://www.ftc.gov/record")

    def test_timeout_is_preserved(self):
        with patch.object(sw.urllib.request, "urlopen", return_value=Response(b"source")) as fetch:
            sw.fetch_url_text("https://www.ftc.gov/record", timeout=3)
        self.assertEqual(fetch.call_args.kwargs["timeout"], 3)


if __name__ == "__main__":
    unittest.main()
