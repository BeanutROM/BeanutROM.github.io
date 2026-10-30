"""Theme regression tests, using only Python's standard library."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


def contrast(foreground, background):
    def luminance(color):
        rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [n / 12.92 if n <= 0.04045 else ((n + .055) / 1.055) ** 2.4 for n in rgb]
        return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]
    a, b = luminance(foreground), luminance(background)
    return (max(a, b) + .05) / (min(a, b) + .05)


class ThemePaletteTests(unittest.TestCase):
    def setUp(self):
        self.css = (ROOT / 'site/styles.css').read_text()

    def test_both_themes_contain_branded_gradients(self):
        self.assertIn('--page-gradient:radial-gradient', self.css)
        self.assertIn('--panel-gradient:linear-gradient', self.css)
        self.assertIn(':root[data-theme="light"]', self.css)
        self.assertIn('#56065d', self.css)
        self.assertIn('#24814b', self.css)
        self.assertIn('#620a68', self.css)
        self.assertIn('#207d4b', self.css)
        self.assertIn('background-image:var(--page-gradient)', self.css)
        self.assertNotIn('--header-gradient:', self.css)
        self.assertNotIn('--control-gradient:', self.css)
        self.assertIn('background:transparent', self.css)

    def test_contrasts(self):
        for foreground, background in (
            ('#f0f8f5', '#1a1a34'),
            ('#c6d5d4', '#1a1a34'),
            ('#9badba', '#1a1a34'),
            ('#8ce9b4', '#1a1a34'),
            ('#281336', '#ffffff'),
            ('#445665', '#ffffff'),
            ('#5c6879', '#ffffff'),
            ('#176c4b', '#ffffff'),
        ):
            self.assertGreaterEqual(contrast(foreground, background), 4.5)

    def test_platform_colors_remain_separate(self):
        palette = json.loads((ROOT / 'platform-colors.json').read_text())
        self.assertIn('PS1', palette)
        self.assertIn('MAME', palette)
        self.assertIn('background:var(--platform-bg', self.css)
        self.assertIn('color:var(--platform-fg', self.css)

    def test_browser_theme_color_tracks_theme(self):
        html = (ROOT / 'site/index.html').read_text()
        js = (ROOT / 'site/app.js').read_text()
        self.assertIn('name="theme-color" content="#100e20"', html)
        self.assertIn("theme === 'dark' ? '#100e20' : '#f2f6f5'", js)


if __name__ == '__main__':
    unittest.main()
