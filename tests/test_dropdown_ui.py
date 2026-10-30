"""Regression checks for configurable branding and custom filter menus.

Pure Python/stdlib to keep GitHub Actions dependency-free.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DropdownUITests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / 'site/index.html').read_text(encoding='utf-8')
        self.css = (ROOT / 'site/styles.css').read_text(encoding='utf-8')
        self.app = (ROOT / 'site/app.js').read_text(encoding='utf-8')

    def test_name_is_configurable_and_defaults_to_requested_brand(self):
        config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
        self.assertEqual(config['site']['name'], 'Beanut Translations')
        self.assertIn('id="brand-logo"', self.html)
        self.assertIn('alt="Beanut Translations"', self.html)
        self.assertIn('const name = String(site.name', self.app)
        self.assertIn("el('brand-logo').alt = name", self.app)
        self.assertIn("el('footer-name').textContent = name", self.app)
        self.assertEqual(json.loads((ROOT / 'site/data/projects.json').read_text())['site']['name'], 'Beanut Translations')

    def test_dropdowns_are_page_rendered_and_styled_without_native_popup(self):
        for field in ('platform', 'status', 'sort'):
            self.assertIn(f'id="{field}-menu" role="listbox"', self.html)
            self.assertIn(f'id="{field}-dropdown"', self.html)
            self.assertIn(f'id="{field}-value"', self.html)
        self.assertNotIn('<select', self.html)
        self.assertIn('aria-haspopup="listbox"', self.html)
        self.assertIn('aria-expanded="false"', self.html)
        self.assertIn('border-radius:0', self.css)
        self.assertIn('.dropdown-menu[hidden] {display:none}', self.css)
        self.assertIn('left:-1px;right:-1px;top:calc(100% - 1px)', self.css)

    def test_advanced_keyboard_navigation_and_filter_sync(self):
        self.assertIn("['ArrowDown', 'ArrowUp', 'Home', 'End', ' ', 'Enter']", self.app)
        for key in ('Escape', 'Tab', 'Home', 'End'):
            self.assertIn(f"event.key === '{key}'", self.app)
        self.assertIn('menu.setAttribute(\'aria-activedescendant\'', self.app)
        self.assertIn("setupDropdown('status', 'status'", self.app)
        self.assertIn("setupDropdown('sort', 'sort'", self.app)
        self.assertIn("setupDropdown('platform', 'platform'", self.app)
        self.assertIn('dropdowns.status.sync(); dropdowns.sort.sync(); dropdowns.platform?.sync();', self.app)
        self.assertIn('state.status = value; state.visible = 12; render();', self.app)
        self.assertIn('state.sort = value; render();', self.app)
        self.assertIn("if (!wrap.contains(event.target)) close();", self.app)


if __name__ == '__main__':
    unittest.main()
