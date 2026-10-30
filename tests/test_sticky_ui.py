"""Desktop sticky controls and non-sticky small-screen layout."""
import re
import unittest
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / 'site/styles.css').read_text()

class StickyLayoutTests(unittest.TestCase):
    def test_larger_logo_and_sticky_header_height(self):
        self.assertIn('.brand-logo {display:block;width:180px;', CSS)
        self.assertIn('--sticky-header-height:132px', CSS)
        self.assertRegex(CSS, r'\.site-header \{[^}]*position:sticky;top:0;z-index:80')

    def test_filters_have_stacked_offset_without_platform_toolbar(self):
        self.assertRegex(CSS, r'\.filters \{[^}]*position:sticky;top:var\(--sticky-header-height\)')
        self.assertNotIn('.filter-toolbar', CSS)
        self.assertIn('html {scroll-padding-top:215px}', CSS)

    def test_sticky_is_disabled_on_mobile_and_tablet(self):
        small = CSS.split('/* On tablets and phones the header and all catalog controls scroll normally. */', 1)[1].split('@media(max-width:540px)', 1)[0]
        self.assertIn('@media(max-width:820px)', small)
        self.assertIn('.site-header {position:relative;top:auto;', small)
        self.assertIn('.filters {position:static;top:auto;', small)
        self.assertIn('html {scroll-padding-top:40px}', small)

if __name__ == '__main__':
    unittest.main()
