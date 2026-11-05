"""Private branding settings, asset safety, and theme-variant installation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build
from scripts.publish_guard import verify_publishable_site

ROOT = Path(__file__).resolve().parents[1]
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 24"><rect width="120" height="24"/></svg>'
SERVICES = ('rss','github','discord','bluesky','kofi')
SUFFIXES = ('','_light','_dark')


class BrandingAssetTests(unittest.TestCase):
    def test_branding_urls_are_separate_from_operational_config(self):
        public_cfg = json.loads((ROOT/'config.json').read_text())
        self.assertNotIn('site', public_cfg)
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp)
            (private/'config.json').write_text('{"discovery":{"owners":["demo"]}}')
            (private/'branding.json').write_text(json.dumps({'site': {
                'discord_url':'https://discord.gg/demo',
                'bluesky_url':'https://bsky.app/profile/demo.bsky.social',
                'kofi_url':'https://ko-fi.com/demo','kofi_label':'Tip here'}}))
            cfg = build.load_config({'CATALOG_PRIVATE_CONFIG_DIR': temp})
            self.assertNotIn('site', cfg)
            site = build.load_site_settings(cfg, {'CATALOG_PRIVATE_CONFIG_DIR':temp})
            self.assertEqual(site['kofi_url'],'https://ko-fi.com/demo')
            self.assertEqual(site['kofi_label'],'Tip here')
            self.assertEqual(site['discord_url'],'https://discord.gg/demo')
            self.assertEqual(site['bluesky_url'],'https://bsky.app/profile/demo.bsky.social')

    def test_new_asset_directory_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)/'private'
            private.mkdir()
            assets=private/'assets'
            assets.mkdir()
            env={'CATALOG_PRIVATE_CONFIG_DIR':str(private)}
            before=build.private_config_fingerprint(env)
            for name in ('logo.png','favicon.png'):
                (assets/name).write_bytes(b'PNG backup sample')
            with patch.object(build,'ROOT',Path(temp)):
                site=build.load_site_settings({'site':{}},env)
                for name,key in (('logo.png','logo_url'),('favicon.png','favicon_url')):
                    self.assertEqual(site[key],f'assets/{name}')
                    self.assertEqual((Path(temp)/'site/assets'/name).read_bytes(),b'PNG backup sample')
            self.assertNotEqual(before,build.private_config_fingerprint(env))

    def test_all_social_variants_are_fingerprinted_and_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)/'private'
            assets=private/'assets'
            assets.mkdir(parents=True)
            env={'CATALOG_PRIVATE_CONFIG_DIR':str(private)}
            hashes=[build.private_config_fingerprint(env)]
            for service in SERVICES:
                for suffix in SUFFIXES:
                    (assets/f'{service}{suffix}.svg').write_bytes(SVG)
                    hashes.append(build.private_config_fingerprint(env))
            self.assertEqual(len(set(hashes)),16)
            with patch.object(build,'ROOT',Path(temp)):
                site=build.load_site_settings({'site':{}},env)
                for service in SERVICES:
                    for suffix in SUFFIXES:
                        filename=f'{service}{suffix}.svg'
                        self.assertEqual(site[f'{service}_icon{suffix}_url'],f'assets/{filename}')
                        self.assertEqual((Path(temp)/'site/assets'/filename).read_bytes(),SVG)
                root=Path(temp)/'site'
                for required in ('index.html','about.html','app.js','styles.css'):
                    (root/required).write_text('public')
                self.assertEqual(verify_publishable_site(root),19)

    def test_missing_variant_then_removal_prunes_public_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)/'private'
            assets=private/'assets'
            assets.mkdir(parents=True)
            env={'CATALOG_PRIVATE_CONFIG_DIR':str(private)}
            (assets/'kofi_dark.svg').write_bytes(SVG)
            with patch.object(build,'ROOT',Path(temp)):
                first=build.load_site_settings({'site':{}},env)
                self.assertEqual(first['kofi_icon_dark_url'],'assets/kofi_dark.svg')
                self.assertNotIn('kofi_icon_url',first)
                (assets/'kofi_dark.svg').unlink()
                second=build.load_site_settings({'site':{}},env)
                self.assertNotIn('kofi_icon_dark_url',second)
                self.assertFalse((Path(temp)/'site/assets/kofi_dark.svg').exists())

    def test_custom_icon_assets_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            private=Path(temp)/'private'
            private.mkdir()
            (private/'assets').symlink_to(Path(temp),target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'symlink'):
                build.load_site_settings({'site':{}},{'CATALOG_PRIVATE_CONFIG_DIR':str(private)})


if __name__ == '__main__':
    unittest.main()
