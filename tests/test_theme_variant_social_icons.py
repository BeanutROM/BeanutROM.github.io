"""theme-aware SVGs, plain-text fallback, and release artifact safety."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build
from scripts.publish_guard import verify_publishable_site

ROOT = Path(__file__).resolve().parents[1]
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#abcdef" d="M0 0h24v24H0z"/></svg>'
SERVICES = ('discord', 'bluesky', 'github')
SUFFIXES = ('', '_light', '_dark')


class ThemeVariantSocialIconTests(unittest.TestCase):
    def test_all_files_fingerprinted_and_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir()
            (private/'assets').mkdir()
            env = {'CATALOG_PRIVATE_CONFIG_DIR': str(private)}
            cfg = {'site': {}}
            fingerprints = [build.private_config_fingerprint(env)]
            for service in SERVICES:
                for suffix in SUFFIXES:
                    (private/'assets'/f'{service}{suffix}.svg').write_bytes(SVG)
                    fingerprints.append(build.private_config_fingerprint(env))
            self.assertEqual(len(set(fingerprints)), 10)
            with patch.object(build, 'ROOT', Path(tmp)):
                site = build.load_site_settings(cfg, env)
                for service in SERVICES:
                    for suffix in SUFFIXES:
                        name = f'{service}{suffix}.svg'
                        key = f'{service}_icon{suffix}_url'
                        self.assertEqual(site[key], f'assets/{name}')
                        self.assertEqual((Path(tmp)/'site/assets'/name).read_bytes(), SVG)
                self.assertEqual(verify_publishable_site(self._make_test_site(tmp)), 13)
                # An icon removed from the private repo disappears from both
                # the generated data and public assets on the next build.
                (private/'assets/github_light.svg').unlink()
                (private/'assets/bluesky.svg').unlink()
                after = build.load_site_settings(cfg, env)
                for name, key in (('github_light.svg','github_icon_light_url'),
                                  ('bluesky.svg','bluesky_icon_url')):
                    self.assertNotIn(key, after)
                    self.assertFalse((Path(tmp)/'site/assets'/name).exists())

    def _make_test_site(self, tmp):
        root = Path(tmp)/'site'
        root.mkdir(exist_ok=True)
        for required in ('index.html','about.html','app.js','styles.css'):
            (root / required).write_text('public')
        return root

    def test_missing_icons_do_not_create_implicit_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp)/'private'
            private.mkdir()
            (private/'assets').mkdir()
            with patch.object(build, 'ROOT', Path(tmp)):
                site = build.load_site_settings({'site': {}}, {'CATALOG_PRIVATE_CONFIG_DIR': str(private)})
                for service in SERVICES:
                    for suffix in SUFFIXES:
                        self.assertNotIn(f'{service}_icon{suffix}_url', site)

    def test_variants_without_base_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp)/'private'
            private.mkdir()
            (private/'assets').mkdir()
            (private/'assets/discord_light.svg').write_bytes(SVG)
            with patch.object(build, 'ROOT', Path(tmp)):
                site = build.load_site_settings({'site': {}}, {'CATALOG_PRIVATE_CONFIG_DIR': str(private)})
                self.assertEqual(site['discord_icon_light_url'], 'assets/discord_light.svg')
                self.assertNotIn('discord_icon_url', site)
                self.assertNotIn('discord_icon_dark_url', site)

    def test_svg_symlink_and_unsafe_variant_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp)/'private'
            private.mkdir()
            (private/'assets').mkdir()
            target = Path(tmp)/'target.svg'
            target.write_bytes(SVG)
            (private/'assets/github_dark.svg').symlink_to(target)
            with patch.object(build, 'ROOT', Path(tmp)):
                with self.assertRaisesRegex(ValueError, 'symlink'):
                    build.load_site_settings({'site': {}}, {'CATALOG_PRIVATE_CONFIG_DIR': str(private)})
            (private/'assets/github_dark.svg').unlink()
            (private/'assets/github_dark.svg').write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>')
            with patch.object(build, 'ROOT', Path(tmp)):
                with self.assertRaisesRegex(ValueError, 'unsupported SVG element'):
                    build.load_site_settings({'site': {}}, {'CATALOG_PRIVATE_CONFIG_DIR': str(private)})


    def test_allowlist_rejects_unknown_svg(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = self._make_test_site(tmp)
            (site/'assets').mkdir()
            for service in SERVICES:
                for suffix in SUFFIXES:
                    (site/'assets'/f'{service}{suffix}.svg').write_bytes(SVG)
            self.assertEqual(verify_publishable_site(site), 13)
            (site/'assets'/'secrets.svg').write_bytes(SVG)
            with self.assertRaisesRegex(ValueError, 'Unexpected file'):
                verify_publishable_site(site)


if __name__ == '__main__':
    unittest.main()
