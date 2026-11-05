"""Security checks for the exact directory uploaded as the public Pages artifact."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from scripts.publish_guard import verify_publishable_site, main


class PublishPayloadTests(unittest.TestCase):
    def site(self, directory):
        root = Path(directory) / 'site'
        root.mkdir()
        for name in ('index.html', 'about.html', 'app.js', 'styles.css'):
            (root / name).write_text(f'public {name}')
        return root

    def test_real_repository_static_bundle_is_allowed(self):
        root = Path(__file__).resolve().parents[1]
        self.assertGreaterEqual(verify_publishable_site(root / 'site'), 4)


    def test_expected_generated_files_are_allowed(self):
        with TemporaryDirectory() as tmp:
            site = self.site(tmp)
            for sub in ('data', 'assets', 'assets/thumbnails'):
                (site / sub).mkdir(exist_ok=True)
            (site/'data'/'projects.json').write_text(json.dumps({'projects': []}))
            (site/'data'/'watch-state.json').write_text('{}')
            (site/'assets'/'logo.png').write_bytes(b'image bytes')
            (site/'assets'/'thumbnails'/('a'*24+'.webp')).write_bytes(b'webp bytes')
            self.assertEqual(verify_publishable_site(site), 8)


    def test_raw_private_files_cannot_be_published(self):
        forbidden = ('config.json', 'branding.json', 'platform-colors.json',
                     'about.md', '.env', 'cache-state.json', 'private-key.pem')
        for name in forbidden:
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                site = self.site(tmp)
                (site/name).write_text('PRIVATE_CONFIG_CANARY')
                with self.assertRaisesRegex(ValueError, 'Unexpected file'):
                    verify_publishable_site(site)

    def test_private_repo_and_reports_cannot_be_nested_in_public_site(self):
        for directory in ('.private-config', '.catalog-cache', 'reports', 'state'):
            with self.subTest(directory=directory), TemporaryDirectory() as tmp:
                site = self.site(tmp)
                (site / directory).mkdir()
                (site / directory / 'config.json').write_text('PRIVATE_CONFIG_CANARY')
                with self.assertRaisesRegex(ValueError, 'Unexpected directory'):
                    verify_publishable_site(site)

    def test_symlink_to_private_file_is_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            private = root/'secret.json'
            private.write_text('PRIVATE_CONFIG_CANARY')
            site = self.site(tmp)
            (site/'data').mkdir()
            (site/'data'/'projects.json').symlink_to(private)
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                verify_publishable_site(site)

    def test_unknown_branding_asset_is_blocked(self):
        with TemporaryDirectory() as tmp:
            site = self.site(tmp)
            (site/'assets').mkdir()
            (site/'assets'/'private-config.json').write_text('PRIVATE_CONFIG_CANARY')
            self.assertEqual(main([str(site)]), 1)

    def test_pages_artifact_only_uploads_validated_site(self):
        # The publication boundary matters; whitespace and step labels do not.
        import re
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/pages.yml').read_text()
        self.assertIn('python -m scripts.publish_guard site', workflow)
        self.assertRegex(workflow, r'actions/upload-pages-artifact@[^\n]*\n\s+with:\s*\n\s+path: site(?:\s|$)')
        self.assertNotIn('actions/upload-artifact@', workflow)


if __name__ == '__main__':
    unittest.main()
