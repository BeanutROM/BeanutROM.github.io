"""Regression checks for unified page background and non-obscuring sticky controls."""
from pathlib import Path
import re
import unittest

CSS = (Path(__file__).resolve().parents[1] / 'site/styles.css').read_text()


class SeamlessSectionTests(unittest.TestCase):
    def test_surfaces_have_no_separate_gradients(self):
        for selector in ('.site-header', '.filters', '.footer'):
            # Top-level rule, not an override in a media query.
            pattern = r'^' + re.escape(selector) + r' \{([^}]*)\}'
            rule = re.search(pattern, CSS, re.M)
            self.assertIsNotNone(rule, selector)
            self.assertIn('background:transparent', rule.group(1))
            self.assertNotIn('gradient(', rule.group(1))
        self.assertNotIn('--header-gradient:', CSS)
        self.assertNotIn('--control-gradient:', CSS)

    def test_sticky_backdrops_share_body_gradient(self):
        self.assertIn('@media(min-width:821px)', CSS)
        self.assertRegex(CSS, r'\.site-header,\.filters \{[^}]*background-image:var\(--page-gradient\);[^}]*background-attachment:fixed')
        self.assertIn('background-image:var(--page-gradient);background-attachment:fixed', CSS)

    def test_mobile_stays_non_sticky_and_transparent(self):
        section = CSS.split('/* On tablets and phones the header and all catalog controls scroll normally. */', 1)[1]
        self.assertIn('.site-header {position:relative;top:auto;', section)
        self.assertIn('background:transparent', section.split('@media(max-width:760px)', 1)[0])
        self.assertIn('.filters {position:static;top:auto;', section)

    def test_controls_and_footer_are_not_tinted(self):
        self.assertRegex(CSS, r'\.search-field,\.select-wrap \{[^}]*background:transparent')
        self.assertRegex(CSS, r'\.footer \{[^}]*background:transparent')
        # Dropdown panel remains opaque to keep text legible.
        self.assertRegex(CSS, r'\.dropdown-menu \{[^}]*background:var\(--surface\)')

if __name__ == '__main__':
    unittest.main()
