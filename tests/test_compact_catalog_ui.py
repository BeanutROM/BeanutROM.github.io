"""Navigation and static total-count regressions."""
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

class CompactCatalogUITests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT/'site/index.html').read_text()
        self.js = (ROOT/'site/app.js').read_text()
        self.css = (ROOT/'site/styles.css').read_text()

    def test_static_total_game_count_in_header(self):
        self.assertIn('id="total-games"', self.html)
        self.assertNotIn('id="result-count"', self.html)
        self.assertIn('state.projects.length} ${state.projects.length === 1', self.js)
        render = self.js.split('function render()', 1)[1].split('function setupPlatforms()',1)[0]
        self.assertNotIn('total-games', render)
        self.assertIn('.brand-count', self.css)

    def test_platform_in_custom_dropdown_and_no_chip_toolbar(self):
        self.assertIn('id="platform-dropdown"', self.html)
        self.assertIn('id="platform-menu" role="listbox"', self.html)
        self.assertNotIn('id="platform-filters"', self.html)
        self.assertNotIn('class="filter-toolbar"', self.html)
        self.assertIn("setupDropdown('platform', 'platform'", self.js)
        self.assertIn('dropdowns.platform?.sync()', self.js)

    def test_one_line_tagline_and_shorter_toolbar(self):
        self.assertIn('white-space:nowrap', self.css.split('.brand-tagline {',1)[1].split('}',1)[0])
        self.assertIn('--sticky-header-height:132px', self.css)
        self.assertIn('.search-wrap', self.css)
        self.assertIn('id="clear-filters"', self.html)
        self.assertIn('.filters {display:grid;grid-template-columns:', self.css)
        self.assertNotIn('.platform-chip', self.css)

if __name__ == '__main__': unittest.main()
