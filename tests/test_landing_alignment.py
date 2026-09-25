"""The generated board carries the shared portfolio header, typography and theme fallback."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build


def render_page():
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "index.html"
        with patch.object(build, "OUT", str(output)), patch("sys.argv", ["build.py"]):
            with contextlib.redirect_stdout(io.StringIO()):
                build.main()
        return output.read_text()


class LandingAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = render_page()

    def test_shared_header_appears_once_before_the_board(self):
        self.assertEqual(self.page.count('<header class="site-header">'), 1)
        body = self.page.split("<body", 1)[1]
        self.assertLess(body.index('<header class="site-header">'), body.index('<div class="wrap">'))
        for href in ("https://nmairesearch.github.io/index.html#work",
                     "https://nmairesearch.github.io/sovereign-watch-case-study.html",
                     "https://nmairesearch.github.io/portfolio-map.html"):
            self.assertIn(f'href="{href}"', self.page)

    def test_alignment_styles_follow_the_board_styles(self):
        self.assertEqual(self.page.count('<style id="landing-alignment">'), 1)
        head = self.page.split("</head>", 1)[0]
        self.assertGreater(head.index('<style id="landing-alignment">'), head.index("--bg-card"))
        self.assertIn('--sans:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif', head)

    def test_theme_colours_are_unchanged(self):
        alignment = self.page.split('<style id="landing-alignment">', 1)[1].split("</style>", 1)[0]
        self.assertNotRegex(alignment, r"#[0-9a-fA-F]{3,6}\b")
        self.assertNotIn("rgb(", alignment)

    def test_stored_theme_wins_and_system_dark_is_the_fallback(self):
        script = self.page.split("<script>", 1)[1].split("</script>", 1)[0]
        stored = script.index("if (t) {")
        fallback = script.index("prefers-color-scheme: dark")
        self.assertLess(stored, fallback)
        self.assertIn("else if", script[stored:fallback])


if __name__ == "__main__":
    unittest.main()
