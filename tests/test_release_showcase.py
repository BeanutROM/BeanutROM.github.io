"""Recent releases are selected by publication time, not repository edits."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from scripts import build

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'site/app.js').read_text(encoding='utf-8')


class ReleasesAPI:
    def __init__(self, releases): self.releases = releases
    def get(self, path, params=None, optional=False): return self.releases


class ReleaseShowcaseTests(unittest.TestCase):
    def test_release_publication_time_does_not_track_older_release_edits(self):
        releases = [
            {'draft': False, 'tag_name': 'v2-beta', 'published_at': '2026-09-20T11:00:00Z',
             'updated_at': '2026-09-20T11:00:00Z'},
            {'draft': False, 'tag_name': 'v1', 'published_at': '2026-01-01T11:00:00Z',
             'updated_at': '2026-10-12T11:00:00Z'},
            {'draft': True, 'tag_name': 'v3', 'published_at': '2026-11-01T11:00:00Z'},
        ]
        api = ReleasesAPI(releases)
        original = build.release_metadata(api, {'owner': {'login': 'sample'}, 'name': 'game'})
        self.assertEqual(len(original), 4)
        self.assertEqual(original[2], 'v2-beta')
        self.assertEqual(original[3], '2026-10-12T11:00:00Z')
        ranked = build.release_metadata(api, {'owner': {'login': 'sample'}, 'name': 'game'}, include_published=True)
        self.assertEqual(ranked[-1], '2026-09-20T11:00:00Z')
        self.assertEqual(build.release_metadata(ReleasesAPI([]), {'owner': {'login': 'sample'}, 'name': 'game'}, include_published=True),
                         (False, '', '', '', ''))


    @unittest.skipUnless(shutil.which('node'), 'Node.js is required to execute actual frontend sorting')
    def test_actual_javascript_limits_to_ten_recent_published_releases(self):
        src = 'function recentReleases() {' + JS.split('  function recentReleases() {', 1)[1].split('  function showcaseCard', 1)[0]
        fixtures = [{'id': f's{i}', 'title': f'Game {i:02}', 'status':'Released', 'release_tag':f'v{i}',
                     'release_published_at':f'2026-10-{i+1:02d}T00:00:00Z',
                     'updated_at':'2026-01-01T00:00:00Z'} for i in range(12)]
        fixtures += [
            {'id':'no-release', 'title':'Not released', 'status':'In-Progress', 'release_tag':'', 'updated_at':'2026-11-04'},
            {'id':'paused', 'title':'Paused', 'status':'Paused', 'release_tag':'v1', 'updated_at':'2026-11-03'},
            {'id':'newer-update', 'title':'Edited repository', 'status':'Released', 'release_tag':'v0.5',
             'release_published_at':'2026-01-01T00:00:00Z', 'updated_at':'2026-11-04T00:00:00Z'},
        ]
        test = '''const vm=require('node:vm');
        const ctx={state:{projects:JSON.parse(process.argv[1])}};
        vm.createContext(ctx); vm.runInContext(process.argv[2],ctx);
        console.log(JSON.stringify(ctx.recentReleases().map(p=>p.id)));
        '''
        res = subprocess.run(['node', '-e', test, json.dumps(fixtures), src],capture_output=True,text=True,check=True)
        expected = [f's{i}' for i in range(11, 1, -1)]
        self.assertEqual(json.loads(res.stdout), expected)


if __name__ == '__main__': unittest.main()
