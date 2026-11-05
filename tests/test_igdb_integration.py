"""Test cover-art priority and description fallback without networking."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'scripts' / 'build.py'
spec = importlib.util.spec_from_file_location('catalog_build', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakeApi:
    def __init__(self, paths=None):
        self.paths = paths or []
    def get(self, path, params=None, optional=False):
        if '/git/trees/' in path:
            return {'tree':[{'type':'blob','path':p} for p in self.paths]}
        if path.endswith('/releases'):
            return []
        return None


class FakeIGDB:
    def __init__(self, game=None):
        self.requests = []
        self.game = game or {'id':123,'name':'Sample Quest','slug':'sample-quest',
                             'cover': {'image_id':'co987'}, 'summary':'IGDB summary.'}
    def get_game(self, title, platform, game_id=None):
        self.requests.append((title, platform, game_id))
        return self.game


def repo():
    return {'full_name':'owner/Sample_Quest_PS2', 'name':'Sample_Quest_PS2',
            'owner':{'login':'owner'}, 'default_branch':'main',
            'description':'Project repo summary', 'topics':['ps2'],
            'html_url':'https://github.com/owner/Sample_Quest_PS2'}


class IntegrationTests(unittest.TestCase):
    def test_igdb_cover_when_no_repo_assets(self):
        igdb = FakeIGDB()
        result = mod.make_project(FakeApi(), repo(), {}, igdb)
        self.assertEqual(result['cover_source'], 'igdb')
        self.assertTrue(result['cover_url'].endswith('/co987.jpg'))
        self.assertEqual(result['screenshots'], [])
        self.assertEqual(result['game_description'], 'IGDB summary.')
        self.assertEqual(result['description_source_url'], 'https://www.igdb.com/games/sample-quest')
        self.assertEqual(igdb.requests, [('Sample Quest', 'PS2', None)])

    def test_igdb_cover_beats_screenshot_but_gallery_remains_local(self):
        result = mod.make_project(FakeApi(['assets/screenshot.png']), repo(), {}, FakeIGDB())
        self.assertEqual(result['cover_source'], 'igdb')
        self.assertEqual(len(result['screenshots']), 1)
        self.assertTrue(result['screenshots'][0].endswith('assets/screenshot.png'))

    def test_repository_cover_wins_over_igdb(self):
        igdb = FakeIGDB()
        result = mod.make_project(FakeApi(['assets/cover.png']), repo(), {}, igdb)
        self.assertEqual(result['cover_source'], 'repository')
        self.assertTrue(result['cover_url'].endswith('assets/cover.png'))
        self.assertEqual(result['game_description'], 'IGDB summary.')

    def test_config_override_wins_over_igdb(self):
        igdb = FakeIGDB()
        overrides = {'owner/Sample_Quest_PS2': {'cover_url':'https://example.org/custom.jpg',
            'game_description':'Curated description', 'igdb_id':123}}
        result = mod.make_project(FakeApi(), repo(), overrides, igdb)
        self.assertEqual(result['cover_url'], 'https://example.org/custom.jpg')
        self.assertEqual(result['game_description'], 'Curated description')
        self.assertEqual(igdb.requests, [])

    def test_manual_id_for_ambiguous_title(self):
        igdb = FakeIGDB()
        overrides = {'owner/Sample_Quest_PS2': {'igdb_id':123, 'igdb_query':'Other Title'}}
        mod.make_project(FakeApi(), repo(), overrides, igdb)
        self.assertEqual(igdb.requests[0], ('Other Title', 'PS2', 123))

    def test_missing_igdb_credentials_preserve_original_fallback(self):
        result = mod.make_project(FakeApi(['assets/screenshot.png']), repo(), {})
        self.assertEqual(result['cover_source'], 'screenshot')
        self.assertTrue(result['cover_url'].endswith('assets/screenshot.png'))

    def test_multi_platform_igdb_lookup_preserves_both(self):
        igdb = FakeIGDB()
        multi = repo()
        multi['name'] = 'Sample_Quest_English_Patch'
        multi['full_name'] = 'owner/Sample_Quest_English_Patch'
        multi['description'] = 'English patch for PCFX and PSX'
        multi['topics'] = []
        result = mod.make_project(FakeApi(), multi, {}, igdb)
        self.assertEqual(result['platforms'], ['PC-FX', 'PS1'])
        self.assertEqual(igdb.requests[0], ('Sample Quest', ['PC-FX', 'PS1'], None))

    def test_igdb_error_does_not_block_project(self):
        igdb = FakeIGDB()
        igdb.get_game = lambda *_: (_ for _ in ()).throw(RuntimeError('temporary outage'))
        with patch('sys.stderr'):
            result = mod.make_project(FakeApi(), repo(), {}, igdb)
        self.assertEqual(result['cover_source'], 'placeholder')
        self.assertEqual(result['game_description'], 'Project repo summary')


if __name__ == '__main__':
    unittest.main()
