"""Verify no identifying site data or images must be stored in the source."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import build

ROOT = Path(__file__).resolve().parents[1]


class ExternalBrandingTests(unittest.TestCase):
    def test_public_config_uses_runtime_identity(self):
        cfg = json.loads((ROOT / 'config.json').read_text())
        self.assertNotIn('site', cfg)
        self.assertEqual(cfg['discovery']['owners'], [])
        self.assertEqual(cfg['discovery']['exclude_repositories'], [])
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp)
            (private/'config.json').write_text(json.dumps({'discovery': {'owners': ['group-one', 'group-two']}, 'overrides': {'group-one/game': {'title': 'Example'}}}))
            effective = build.load_config({'GITHUB_REPOSITORY': 'demo-owner/demo-owner.github.io',
                                           'CATALOG_PRIVATE_CONFIG_DIR': str(private)})
        self.assertEqual(effective['discovery']['owners'], ['group-one', 'group-two'])
        self.assertEqual(effective['discovery']['exclude_repositories'], ['demo-owner/demo-owner.github.io'])
        self.assertEqual(effective['overrides']['group-one/game']['title'], 'Example')
        self.assertEqual(build.load_config({'GITHUB_REPOSITORY': 'DEMO-OWNER/Demo-Owner.github.io'})
                         ['discovery']['exclude_repositories'], ['DEMO-OWNER/Demo-Owner.github.io'])

    def test_actions_json_branding_without_files(self):
        site = build.load_site_settings({'site': {}}, {
            'CATALOG_SITE_JSON': '{"name":"Example Site","tagline":"Example tagline",'
                                 '"kofi_url":"https://example.com/support"}'})
        self.assertEqual(site['name'], 'Example Site')
        self.assertEqual(site['tagline'], 'Example tagline')
        self.assertEqual(site['kofi_url'], 'https://example.com/support')
        self.assertEqual(site['logo_url'], 'assets/default-icon.svg')
        self.assertEqual(build.load_platform_colors({
            'CATALOG_PLATFORM_COLORS_JSON': '{"PS1":{"background":"#123456","text":"#ffffff"}}'
        })['PS1']['background'], '#123456')

    def test_private_branding_inputs_and_variable_override(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            private = temp / 'private'
            private.mkdir()
            (private/'branding.json').write_text(json.dumps({'site': {'name': 'From private', 'tagline':'Private'}}))
            (private/'platform-colors.json').write_text(json.dumps({'PS1': {'background':'#123456', 'text':'#ffffff'}}))
            (private/'assets').mkdir()
            for image in ('logo.png','favicon.png'):
                (private/'assets'/image).write_bytes(b'example png bytes')
            (private/'theme.css').write_bytes(b'example css')
            with patch.object(build, 'ROOT', temp):
                env = {'CATALOG_PRIVATE_CONFIG_DIR': str(private),
                       'CATALOG_SITE_JSON': '{"name":"From variable"}',
                       'CATALOG_PLATFORM_COLORS_JSON': '{"MAME":{"background":"#000000","text":"#ffffff"}}'}
                site = build.load_site_settings({'site': {}}, env)
                self.assertEqual(site['name'], 'From variable')
                self.assertEqual(site['tagline'], 'Private')
                for image, key in [('logo.png','logo_url'),('favicon.png','favicon_url'),
                                   ('theme.css','theme_url')]:
                    self.assertEqual(site[key], 'assets/' + image)
                    self.assertEqual((temp/'site/assets'/image).read_bytes(), b'example css' if image == 'theme.css' else b'example png bytes')
                self.assertEqual(list(build.load_platform_colors(env)), ['MAME'])
                self.assertIn('PS1', build.load_platform_colors({'CATALOG_PRIVATE_CONFIG_DIR':str(private)}))

    def test_reject_bad_json_and_invalid_colors(self):
        with self.assertRaises(ValueError):
            build.load_site_settings({'site': {}}, {'CATALOG_SITE_JSON':'[1,2,3]'})
        with self.assertRaises(ValueError):
            build.load_platform_colors({'CATALOG_PLATFORM_COLORS_JSON':
                '{"PS1":{"background":"red","text":"#ffffff"}}'})

    def test_public_html_does_not_embed_identity(self):
        html = (ROOT/'site/index.html').read_text()
        self.assertIn('id="brand-logo"', html)
        self.assertIn('id="support-link"', html)
        self.assertIn('id="site-favicon"', html)
        self.assertNotIn('src="assets/logo.png"', html)
        self.assertIn('Other', json.loads((ROOT/'platform-colors.json').read_text()))
        self.assertFalse((ROOT/'site/assets/logo.png').exists())

if __name__ == '__main__':
    unittest.main()
