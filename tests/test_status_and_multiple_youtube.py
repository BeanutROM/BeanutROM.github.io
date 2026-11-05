"""Root status and explicit multi-video gallery regression tests."""
import unittest
from pathlib import Path
from scripts import build, watch
from scripts.youtube import associate_videos
from test_build import FakeApi, example


def url(video_id):
    return 'https://www.youtube.com/watch?v=' + video_id


class StatusAndMultipleYouTubeTests(unittest.TestCase):
    def test_root_status_without_assets_folder(self):
        class RootOnly(FakeApi):
            def get(self, path, params=None, optional=False):
                if '/git/trees/' in path:
                    return {'tree': [{'type':'blob','path':'README.md'},
                                     {'type':'blob','path':'status.txt'}]}
                return super().get(path, params, optional)
        api = RootOnly()
        api.asset_texts = {'status.txt': 'pAuSeD\r\n'}
        self.assertEqual(build.make_project(api, example(), {})['status'], 'Paused')

    def test_root_status_with_truncated_tree(self):
        class Truncated(FakeApi):
            def get(self, path, params=None, optional=False):
                if '/git/trees/' in path:
                    return {'truncated': True, 'tree': [{'type':'blob','path':'README.md'}]}
                return super().get(path, params, optional)
        api = Truncated()
        api.asset_texts = {'status.txt': 'Paused'}
        self.assertEqual(build.make_project(api, example(), {})['status'], 'Paused')

    def test_ten_explicit_urls_preserve_order_and_original_first(self):
        ids = [f'A{i:010d}' for i in range(12)]
        raw = '# example\n\n' + '\n'.join(url(i) for i in ids)
        api = FakeApi()
        api.asset_texts = {'assets/youtube.txt': raw}
        project = build.make_project(api, example(), {})
        self.assertEqual(project['youtube_urls'], [url(x) for x in ids[:10]])

    def test_invalid_and_duplicates_do_not_consume_ten_slots(self):
        ids = [f'B{i:010d}' for i in range(10)]
        raw = '\n'.join(['# videos', 'javascript:alert(1)', 'https://youtu.be/' + ids[0],
                         url(ids[0]), '', 'https://www.evil.com/watch?v=123456789AB',
                         *[url(i) for i in ids[1:]]])
        self.assertEqual(build.parse_youtube_urls(raw), [url(x) for x in ids])

    def test_channel_duplicate_against_second_manual_video(self):
        ids = ['abcdefghijk', '123456789AB', 'zxcvbnmasdf']
        project = {'repo': 'alice/game', 'title': 'Sample Quest',                    'youtube_urls': [url(ids[0]), url(ids[1])]}
        associate_videos([project], [{'id': ids[1], 'title': 'Sample Quest gameplay'},
                                     {'id': ids[2], 'title': 'Sample Quest PS1 English Patch'}])
        self.assertEqual([v['url'] for v in project['youtube_videos']], [url(ids[2])])

    def test_watcher_carries_explicit_urls_and_avoids_duplicates(self):
        ids = ['abcdefghijk', '123456789AB']
        repo = {'full_name': 'alice/game', 'pushed_at': '2026-11-01T01:00:00Z'}
        project = {'repo': 'alice/game', 'title': 'Sample Quest', 'youtube_urls': [url(x) for x in ids],
                   }
        snapshot = watch.build_snapshot([repo], [project], {'status':'complete', 'videos':[]})
        self.assertEqual(snapshot['youtube']['projects'][0]['youtube_urls'], [url(x) for x in ids])
        self.assertEqual(watch.video_changes(snapshot, [{'id': ids[1], 'title':'Sample Quest English Patch'}]), [])

    def test_frontend_reads_canonical_video_list(self):
        js = (Path(__file__).resolve().parents[1] / 'site/app.js').read_text()
        self.assertIn('Array.isArray(p.youtube_urls)', js)
        self.assertIn('explicitVideos.forEach(url => addVideo', js)
        self.assertNotIn('[p.youtube_url, ...explicitVideos]', js)
        self.assertIn('seenVideos.has(id)', js)


if __name__ == '__main__':
    unittest.main()
