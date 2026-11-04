"""Feed intake preserves its last output when every source fails."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import fetch_feeds


class FeedFailureTests(unittest.TestCase):
    def run_intake(self, target, responses):
        feeds = [(f"https://example.test/feed{index}", False)
                 for index in range(len(responses))]
        with mock.patch.object(fetch_feeds, "OUT", str(target)), \
                mock.patch.object(fetch_feeds, "FEEDS", feeds), \
                mock.patch.object(fetch_feeds.urllib.request, "urlopen",
                                  side_effect=responses), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            fetch_feeds.main()

    def test_total_failure_preserves_existing_feed_and_timestamp(self):
        for failure in (OSError("feed unavailable"),
                        mock.Mock(read=mock.Mock(return_value=b"not XML"))):
            with self.subTest(failure=type(failure).__name__), \
                    tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "feed_items.json"
                prior = b'{"fetched": "2000-01-01 00:00 UTC", "items": [{"headline": "Kept"}]}\n'
                target.write_bytes(prior)
                with self.assertRaises(SystemExit) as raised:
                    self.run_intake(target, [failure])
                self.assertNotEqual(raised.exception.code, 0)
                self.assertEqual(target.read_bytes(), prior)

    def test_total_failure_does_not_create_a_fresh_empty_feed(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "feed_items.json"
            with self.assertRaises(SystemExit) as raised:
                self.run_intake(target, [OSError("feed unavailable")])
            self.assertNotEqual(raised.exception.code, 0)
            self.assertFalse(target.exists())

    def test_successful_empty_feed_is_written_even_if_another_source_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "feed_items.json"
            target.write_text('{"fetched": "old", "items": [{"headline": "Old"}]}')
            empty_feed = mock.Mock(read=mock.Mock(return_value=b"<rss><channel/></rss>"))
            self.run_intake(target, [OSError("feed unavailable"), empty_feed])
            actual = json.loads(target.read_text())
            self.assertEqual(actual["items"], [])
            self.assertNotEqual(actual["fetched"], "old")


if __name__ == "__main__":
    unittest.main()
