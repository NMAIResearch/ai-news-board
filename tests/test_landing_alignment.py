"""The generated board carries the shared portfolio header, typography and theme fallback."""

import contextlib
import io
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build


# The main site's base palette, from portfolio.css at the site's commit 093dedf (lines 2, 3, 34 and 35).
SITE_LIGHT = {"--bg": "#fff", "--surface": "#fff", "--raised": "#f7fafc", "--text": "#2d3748", "--muted": "#4a5568",
              "--line": "#e2e8f0", "--accent": "#2b6cb0", "--heading": "#1a365d", "--tag": "#f7fafc",
              "--glass": "rgba(247,250,252,.8)"}
SITE_DARK = {"--bg": "#0f141d", "--surface": "#161d2b", "--raised": "#161d2b", "--text": "#e8edf4", "--muted": "#a0aec0",
             "--line": "#2a3444", "--accent": "#63b3ed", "--heading": "#e2e8f0", "--tag": "#161d2b",
             "--glass": "rgba(22,29,43,.74)"}
# Every colour in the alignment layer of the approved redesign (90a8270).
APPROVED_COLOURS = {"#0f141d", "#161d2b", "#1a365d", "#1e293b", "#2a3444", "#2b6cb0", "#2d3748", "#4a5568", "#63b3ed",
                    "#a0aec0", "#e2e8f0", "#e8edf4", "#f1f5f9", "#f7fafc", "#fff", "rgba(0,0,0,.35)", "rgba(0,0,0,.8)",
                    "rgba(128,128,128,.22)", "rgba(16,34,64,.05)", "rgba(16,34,64,.28)", "rgba(22,29,43,.74)",
                    "rgba(247,250,252,.8)"}


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
        header = body.split('<header class="site-header">', 1)[1].split("</header>", 1)[0]
        # The main site's brand link and its five vault links (redesign 90a8270, 18 October 2026), in the header itself.
        for href in ("https://nmairesearch.com/",
                     "https://nmairesearch.com/research.html",
                     "https://nmairesearch.com/software-vault/",
                     "https://nmairesearch.com/game-vault/",
                     "https://nmairesearch.com/music-vault/",
                     "https://nmairesearch.com/video-vault/"):
            self.assertIn(f'href="{href}"', header)

    def test_alignment_styles_follow_the_board_styles(self):
        self.assertEqual(self.page.count('<style id="landing-alignment">'), 1)
        head = self.page.split("</head>", 1)[0]
        self.assertGreater(head.index('<style id="landing-alignment">'), head.index("--bg-card"))
        self.assertIn('--sans:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif', head)

    def test_theme_colours_match_the_main_site(self):
        # Until 18 October 2026 this test required the alignment layer to add no colours. The redesign N. asked for
        # (90a8270) gives the board the main site's palette instead, so the test now pins that palette and the full set
        # of colours the approved redesign uses: any new or changed colour still fails.
        alignment = self.page.split('<style id="landing-alignment">', 1)[1].split("</style>", 1)[0]
        rules = {m.group(1).strip(): m.group(2) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", alignment)}
        light = rules[':root,html[data-theme="light"]']
        dark_rules = (rules[':root[data-theme="dark"],html[data-theme="dark"]'], rules[':root:not([data-theme="light"])'])
        for token, value in SITE_LIGHT.items():
            self.assertIn(f"{token}:{value};", light + ";")
        for dark in dark_rules:
            for token, value in SITE_DARK.items():
                self.assertIn(f"{token}:{value};", dark + ";")
        colours = set(re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)", alignment))
        self.assertEqual(colours - APPROVED_COLOURS, set())

    def test_stored_theme_wins_and_system_dark_is_the_fallback(self):
        script = self.page.split("<script>", 1)[1].split("</script>", 1)[0]
        stored = script.index("if (t) {")
        fallback = script.index("prefers-color-scheme: dark")
        self.assertLess(stored, fallback)
        self.assertIn("else if", script[stored:fallback])


if __name__ == "__main__":
    unittest.main()
