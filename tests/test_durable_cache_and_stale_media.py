"""persistent cache and removal safety regression tests."""
from __future__ import annotations
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import build, cache_state, media_validation, rss_feed, thumbnails, watch
from tests.test_thumbnails import FakeResponse, png_sample, URL

ROOT = Path(__file__).resolve().parents[1]
SHA_A = 'a' * 40
SHA_B = 'b' * 40
YOUTUBE_ID = 'aBcDeFg1234'
VIDEO_URL = 'https://www.youtube.com/watch?v=' + YOUTUBE_ID


class DurableMediaTests(unittest.TestCase):
    def project(self, revision=SHA_A):
        return {'repo': 'alice/game', 'screenshots': [URL], 'cover_url': URL,
                '_screenshot_revisions': {URL: revision}}

    def test_thumbnail_restores_only_when_source_blob_matches(self):
        if not thumbnails._converter():
            self.skipTest('ImageMagick is unavailable')
        payload = png_sample()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            one = self.project()
            with patch('scripts.thumbnails.urlopen', return_value=FakeResponse(payload)):
                stats = thumbnails.generate_thumbnails([one], root / 'first', cache_dir=root / 'cache')
            self.assertEqual(stats['generated'], 1)
            self.assertEqual(len(list((root/'cache'/'thumbnails').glob('*.webp'))), 1)
            original_key = Path(one['screenshot_thumbnails'][0]).name
            two = self.project()
            with patch('scripts.thumbnails.urlopen', side_effect=AssertionError('unexpected download')):
                stats = thumbnails.generate_thumbnails([two], root/'second', cache_dir=root/'cache')
            self.assertEqual(stats['cached'], 1)
            self.assertEqual(two['screenshot_thumbnails'], one['screenshot_thumbnails'])
            self.assertEqual(two['screenshot_dimensions'], [[640, 480]])
            self.assertTrue((root/'second'/original_key).exists())

    def test_changed_blob_invalidates_same_url_and_prunes_old_cache(self):
        if not thumbnails._converter():
            self.skipTest('ImageMagick is unavailable')
        payload = png_sample()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p1 = self.project(SHA_A)
            p2 = self.project(SHA_B)
            with patch('scripts.thumbnails.urlopen', side_effect=lambda *a, **kw: FakeResponse(payload)) as opener:
                thumbnails.generate_thumbnails([p1], root/'a', cache_dir=root/'cache')
                thumbnails.generate_thumbnails([p2], root/'b', cache_dir=root/'cache')
            self.assertEqual(opener.call_count, 2)
            self.assertNotEqual(p1['screenshot_thumbnails'], p2['screenshot_thumbnails'])
            files = list((root/'cache'/'thumbnails').glob('*.webp'))
            self.assertEqual([p.name for p in files], [Path(p2['screenshot_thumbnails'][0]).name])

    def test_corrupted_cached_webp_does_not_skip_fresh_conversion(self):
        if not thumbnails._converter():
            self.skipTest('ImageMagick is unavailable')
        payload = png_sample()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self.project()
            with patch('scripts.thumbnails.urlopen', return_value=FakeResponse(payload)):
                thumbnails.generate_thumbnails([first], root/'first', cache_dir=root/'cache')
            cache_files = list((root/'cache'/'thumbnails').glob('*.webp'))
            cache_files[0].write_bytes(b'RIFFNOT-AN-IMAGE')
            with patch('scripts.thumbnails.urlopen', return_value=FakeResponse(payload)) as opener:
                stats = thumbnails.generate_thumbnails([self.project()], root/'second', cache_dir=root/'cache')
            self.assertEqual(opener.call_count, 1)
            self.assertEqual(stats['generated'], 1)

    def test_removed_github_screenshot_does_not_come_back_from_cache(self):
        class API:
            def get(self, path, params=None, optional=False):
                if '/git/trees/' in path:
                    return {'tree': []}
                return []
        repo = {'owner': {'login': 'alice'}, 'name': 'game', 'default_branch': 'main'}
        result = build.find_media(API(), repo, {})
        self.assertEqual(result[1], [])
        with tempfile.TemporaryDirectory() as tmp:
            p = {'repo': 'alice/game', 'screenshots': []}
            thumbnails.generate_thumbnails([p], Path(tmp)/'site', cache_dir=Path(tmp)/'cache')
            self.assertEqual(p['screenshot_thumbnails'], [])
            self.assertEqual(list((Path(tmp)/'site').glob('*.webp')), [])

    def test_broken_source_404_is_removed_instead_of_fallback_dead_link(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch('scripts.thumbnails._converter', return_value='convert'), \
             patch('scripts.thumbnails._fetch_image', side_effect=HTTPError(URL, 404, 'Not found', {}, None)):
            p = self.project(revision='')
            stats = thumbnails.generate_thumbnails([p], Path(tmp))
            self.assertEqual(stats['removed'], 1)
            self.assertEqual(p['screenshots'], [])
            self.assertEqual(p['screenshot_thumbnails'], [])
            self.assertEqual(p['cover_url'], '')

    def test_live_tree_sha_populates_revision_mapping(self):
        class API:
            def get(self, path, params=None, optional=False):
                if '/git/trees/' in path:
                    return {'tree': [{'path': 'assets/screenshots/01.png', 'type': 'blob', 'sha': SHA_A}]}
                return None
        repo = {'owner': {'login': 'alice'}, 'name': 'game', 'default_branch': 'main'}
        revisions = {}
        _, screenshots, *_ = build.find_media(API(), repo, revisions)
        self.assertEqual(len(screenshots), 1)
        self.assertEqual(revisions[screenshots[0]], SHA_A)

    def test_no_private_cache_staging_into_public_actions_artifacts(self):
        """Cache state can only be written directly to the private checkout."""
        self.assertFalse(hasattr(cache_state, 'stage_cache'))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_root = root/'private-checkout'/'state'
            (root/'feed.xml').write_text('<rss/>')
            (root/'projects.json').write_text('{"projects":[]}')
            cache_state.save_history(cache_root, root/'feed.xml', root/'projects.json')
            self.assertTrue((cache_root/'rss'/'feed.xml').is_file())
            self.assertFalse((root/'reports'/'cache-update').exists())


class VideoRemovalTests(unittest.TestCase):
    def test_deleted_youtube_video_excluded_from_explicit_and_channel(self):
        good = 'https://www.youtube.com/watch?v=bbbbbbbbbbb'
        p = {'youtube_urls': [VIDEO_URL, good],
             'youtube_videos': [{'url': VIDEO_URL, 'title': 'Bad'}, {'url': good, 'title': 'Good'}]}
        status = media_validation.remove_unavailable_videos([p], 'fake',
            status_provider=lambda ids, key: {YOUTUBE_ID: False, 'bbbbbbbbbbb': True})
        self.assertEqual(status['removed'], 2)
        self.assertEqual(p['youtube_urls'], [good])
        self.assertEqual(p['youtube_videos'], [{'url': good, 'title': 'Good'}])

    def test_api_unavailable_fails_closed_without_claiming_deletion(self):
        p = {'youtube_urls': [VIDEO_URL], 'youtube_videos': []}
        status = media_validation.remove_unavailable_videos([p], 'fake',
            status_provider=lambda ids, key: {YOUTUBE_ID: None})
        self.assertEqual(status['unverified'], 1)
        self.assertEqual(status['removed'], 0)
        self.assertEqual(p['youtube_urls'], [])

    def test_api_video_lookup_requires_public_and_embeddable(self):
        data = {'items': [
            {'id': YOUTUBE_ID, 'status': {'privacyStatus': 'public', 'embeddable': True}},
            {'id': 'bbbbbbbbbbb', 'status': {'privacyStatus': 'public', 'embeddable': False}},
        ]}
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        with patch('scripts.media_validation.urlopen', return_value=Response(json.dumps(data).encode())) as opener:
            result = media_validation.check_videos([YOUTUBE_ID, 'bbbbbbbbbbb', 'ccccccccccc'], api_key='secret')
        self.assertEqual(result, {YOUTUBE_ID: True, 'bbbbbbbbbbb': False, 'ccccccccccc': False})
        self.assertIn('part=status', opener.call_args.args[0].full_url)

    def test_watch_rebuilds_for_confirmed_missing_but_not_unknown(self):
        snap = {'youtube': {'published_ids': [YOUTUBE_ID]}}
        with patch('scripts.watch.check_videos', return_value={YOUTUBE_ID: False}):
            reasons = watch.missing_video_changes(snap, api_key='fake')
            self.assertEqual(len(reasons), 1)
            self.assertIn(YOUTUBE_ID, reasons[0])
        with patch('scripts.watch.check_videos', return_value={YOUTUBE_ID: None}):
            self.assertEqual(watch.missing_video_changes(snap, api_key='fake'), [])

    def test_scheduled_video_checks_are_bounded_even_with_api_key(self):
        ids = [f'{n:011d}' for n in range(350)]
        snap = {'youtube': {'published_ids': ids}}
        checked = []
        def provider(batch, key):
            checked.extend(batch)
            return {entry: True for entry in batch}
        with patch('scripts.watch.check_videos', side_effect=provider):
            reasons = watch.missing_video_changes(snap, api_key='key', slot=2)
        self.assertEqual(reasons, [])
        self.assertEqual(len(checked), 100)
        self.assertEqual(checked[0], ids[200])
        checked.clear()
        with patch('scripts.watch.check_videos', side_effect=provider):
            watch.missing_video_changes(snap, api_key='', slot=2)
        self.assertEqual(len(checked), 20)
        self.assertEqual(checked[0], ids[40])

    def test_live_snapshot_tracks_only_published_video_ids(self):
        repo = {'full_name': 'alice/game', 'pushed_at': '2026-01-01T00:00:00Z'}
        project = {'repo': 'alice/game', 'title': 'Game', 'youtube_urls': [VIDEO_URL],
                   'youtube_videos': [{'url': 'https://www.youtube.com/watch?v=bbbbbbbbbbb'}]}
        with patch('scripts.watch.private_config_fingerprint', return_value='a'):
            result = watch.build_snapshot([repo], [project], {'status': 'missing_channel'})
        self.assertEqual(result['youtube']['published_ids'], [YOUTUBE_ID, 'bbbbbbbbbbb'])


class RSSAndWorkflowTests(unittest.TestCase):
    def test_cache_rss_used_when_published_site_unreachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root/'state'/'rss'
            cache.mkdir(parents=True)
            old = {'repo': 'alice/game', 'title': 'Game', 'status': 'In-Progress',
                   'has_release': False, 'updated_at': '2026-10-01T00:00:00Z'}
            cache.joinpath('projects.json').write_text(json.dumps({'projects': [old]}))
            rss_feed.write_rss([], {'name': 'Catalog'}, cache/'feed.xml')
            new = dict(old, status='Paused', updated_at='2026-11-01T00:00:00Z',
                       github_url='https://github.com/alice/game')
            env = {'CATALOG_CACHE_DIR': str(root/'state'), 'GITHUB_REPOSITORY': 'alice/alice.github.io'}
            with patch('scripts.rss_feed.fetch_published', side_effect=RuntimeError('temporary outage')):
                count = rss_feed.build_rss_feed([new], {'name':'Catalog'}, root/'out.xml', env)
            self.assertEqual(count, 1)
            self.assertIn(b'Status change', (root/'out.xml').read_bytes())

    def test_workflow_cache_is_opt_in_and_committed_after_successful_pages_deploy(self):
        workflow = (ROOT/'.github/workflows/pages.yml').read_text()
        self.assertIn('CATALOG_CACHE_REPOSITORY', workflow)
        self.assertIn('CATALOG_CACHE_TOKEN', workflow)
        self.assertIn('persist-credentials: false', workflow)
        self.assertNotIn('rsync -a --delete .cache-update/state/ .catalog-cache/state/', workflow)
        self.assertNotIn('actions/upload-artifact@', workflow)
        self.assertIn('git -C .catalog-cache add -A -- state/', workflow)
        self.assertGreater(workflow.index('name: Save durable cache state after deployment'),
                           workflow.index('name: Deploy GitHub Pages'))
        self.assertNotIn('actions/cache@', workflow)


if __name__ == '__main__':
    unittest.main()
