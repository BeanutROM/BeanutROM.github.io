"""Basic regression checks for the one-page site header."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HeaderUITests(unittest.TestCase):
    def test_site_header_uses_image_instead_of_text_breadcrumb(self):
        html = (ROOT / 'site/index.html').read_text()
        self.assertIn('id="brand-logo"', html)
        self.assertIn('src="assets/beanut-logo.png"', html)
        self.assertIn('alt="Beanut Translations"', html)
        self.assertIn('<span class="brand-tagline">AI Translations made with Human love</span>', html)
        self.assertGreater(html.index('class="brand-tagline"'), html.index('id="brand-logo"'))
        self.assertNotIn('id="brand-name"', html)
        self.assertNotIn('/ GAMES', html)
        self.assertNotIn('THE ARCHIVE', html)
        self.assertNotIn('catalog-owner', html)
        self.assertIn('id="games" aria-label="Game catalog"', html)
        self.assertNotIn('id="games-heading"', html)
        self.assertNotIn('class="library-heading-row"', html)

    def test_kofi_link_uses_supplied_button(self):
        html = (ROOT / 'site/index.html').read_text()
        css = (ROOT / 'site/styles.css').read_text()
        asset = ROOT / 'site/assets/kofi-button.png'
        self.assertTrue(asset.is_file())
        self.assertIn('href="https://ko-fi.com/beanutroms/tip"', html)
        self.assertIn('src="assets/kofi-button.png"', html)
        self.assertIn('alt="Support me on Ko-fi"', html)
        self.assertIn('width="980" height="198"', html)
        self.assertIn('.kofi-link img', css)
        self.assertLess(html.index('id="nav-github"'), html.index('class="kofi-link"'))
        self.assertLess(html.index('class="kofi-link"'), html.index('id="theme-toggle"'))
        # PNG dimensions are stored in the IHDR chunk. No third-party imaging
        # library is needed just to verify a committed static asset.
        png = asset.read_bytes()
        self.assertGreaterEqual(len(png), 24)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(png[12:16], b"IHDR")
        size = (int.from_bytes(png[16:20], "big"),
                int.from_bytes(png[20:24], "big"))
        self.assertEqual(size, (980, 198))

    def test_no_games_intro_copy(self):
        html = (ROOT / 'site/index.html').read_text()
        self.assertNotIn('Explore game projects, screenshots, videos, and the latest releases.', html)

    def test_no_sync_ui_or_dead_javascript_references(self):
        html = (ROOT / 'site/index.html').read_text()
        js = (ROOT / 'site/app.js').read_text()
        css = (ROOT / 'site/styles.css').read_text()
        for removed in ('sync-label', 'sync-date', 'collection-status', 'Catalog synchronized'):
            self.assertNotIn(removed, html + js + css)

    def test_logo_is_responsive(self):
        css = (ROOT / 'site/styles.css').read_text()
        self.assertIn('.brand-logo {display:block;', css)
        self.assertIn('.brand-logo {display:block;width:180px;', css)
        self.assertIn('.brand-logo {width:clamp(118px,29vw,165px)}', css)
        self.assertNotIn('.brand-symbol', css)
        self.assertIn('.brand-tagline {display:block;white-space:nowrap;', css)
        self.assertIn('@media(max-width:820px) {\n  html {scroll-padding-top:40px}', css)
        self.assertIn('  .site-header {flex-wrap:wrap}', css)

    def test_supplied_png_assets_are_used_without_pillow(self):
        html = (ROOT / 'site/index.html').read_text()
        js = (ROOT / 'site/app.js').read_text()
        self.assertIn('type="image/png" sizes="256x256" href="assets/favicon.png"', html)
        self.assertIn("el('brand-logo').alt = name", js)
        for name, expected_size in (('favicon.png', (256, 256)), ('beanut-logo.png', (1347, 842))):
            data = (ROOT / 'site/assets' / name).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(data[12:16], b'IHDR')
            size = (int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big'))
            self.assertEqual(size, expected_size)
            self.assertEqual(data[25], 6, 'Images must retain RGBA transparency')


if __name__ == '__main__':
    unittest.main()
