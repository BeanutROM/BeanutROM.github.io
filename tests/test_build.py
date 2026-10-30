import base64
import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'scripts' / 'build.py'
spec = importlib.util.spec_from_file_location('catalog_build', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def example(name='translation', description='English fan translation of Example Game (PS2)',
            topics=None, releases=None, fork=False):
    return {
        'name': name, 'full_name': 'alice/' + name, 'description': description,
        'topics': topics if topics is not None else ['fan-translation', 'ps2'],
        'fork': fork, 'private': False, 'default_branch': 'main',
        'owner': {'login': 'alice'}, 'html_url': 'https://github.com/alice/' + name,
        'pushed_at': '2026-09-20T00:00:00Z', 'stargazers_count': 9,
        'has_issues': True, 'archived': False
    }


class FakeApi:
    def __init__(self, repos=None, releases=None):
        self.repos = repos or []
        self.releases = releases or []
        self.paths = []
        self.asset_texts = {}

    def get(self, path, params=None, optional=False):
        self.paths.append(path)
        if path == '/users/alice':
            return {'type': 'User'}
        if '/users/' in path or '/orgs/' in path:
            return self.repos
        if '/search/' in path:
            return {'items': self.repos}
        if path.endswith('/releases'):
            return self.releases
        if '/git/trees/' in path:
            return {'tree': [
                {'type': 'blob', 'path': 'docs/cover.jpg'},
                {'type': 'blob', 'path': 'docs/screenshots/02.png'},
                {'type': 'blob', 'path': 'docs/screenshots/01.png'},
                *({'type':'blob','path':asset} for asset in self.asset_texts)
            ]}
        if '/contents/' in path:
            content = self.asset_texts.get(path.split('/contents/', 1)[1])
            if content is not None:
                return {'encoding':'base64','content':base64.b64encode(content.encode()).decode()}
            return None
        if path.startswith('/repos/'):
            return self.repos[0] if self.repos else None
        return None


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            'discovery': {
                'owners': [], 'include_topics_any': ['fan-translation'],
                'include_description_matches': ['english translation'],
                'include_repositories': [], 'exclude_repositories': [],
                'include_forks': False, 'search_queries': [], 'max_projects': 50
            }, 'overrides': {}
        }

    def test_owner_fallback_and_topic_selection(self):
        yes = example()
        no = example(name='misc', description='unrelated toolkit', topics=['rust'])
        found = mod.discover_repos(FakeApi([yes, no]), self.config, 'alice')
        self.assertEqual([r['name'] for r in found], ['translation'])

    def test_exclusions_override_explicit_inclusion(self):
        self.config['discovery']['include_repositories'] = ['alice/translation']
        self.config['discovery']['exclude_repositories'] = ['alice/translation']
        found = mod.discover_repos(FakeApi([example()]), self.config, 'alice')
        self.assertEqual(found, [])

    def test_releases_classification(self):
        repo = example()
        stable = {'draft': False, 'prerelease': False, 'html_url': 'https://example.org/v1', 'tag_name': 'v1'}
        beta = {'draft': False, 'prerelease': True, 'html_url': 'https://example.org/beta', 'tag_name': 'b1'}
        self.assertTrue(mod.recent_release(FakeApi(releases=[beta, stable]), repo)[0])
        self.assertTrue(mod.recent_release(FakeApi(releases=[beta]), repo)[0])
        self.assertEqual(mod.recent_release(FakeApi(releases=[stable]), repo)[2], 'v1')
        self.assertFalse(mod.recent_release(FakeApi(releases=[]), repo)[0])

    def test_art_discovery_and_sort_order(self):
        cover, shots = mod.find_art(FakeApi(), example())
        self.assertTrue(cover.endswith('/docs/cover.jpg'))
        self.assertTrue(shots[0].endswith('/01.png'))
        self.assertEqual(len(shots), 2)

    def test_overrides_and_metadata(self):
        overrides = {'alice/translation': {'title': 'Custom title', 'status': 'Released', 'featured': True}}
        project = mod.make_project(FakeApi(), example(), overrides)
        self.assertEqual(project['title'], 'Custom title')
        self.assertEqual(project['status'], 'In-Progress')  # Must not be faked by an override.
        self.assertFalse(project['has_release'])
        self.assertTrue(project['featured'])
        self.assertEqual(project['platform'], 'PS2')
        self.assertEqual(project['stars'], 9)

    def test_media_indexed_from_assets_and_youtube_txt(self):
        api = FakeApi()
        api.asset_texts = {
            'assets/youtube.txt': 'https://youtu.be/dQw4w9WgXcQ',
            'assets/description.txt': 'Game plot description.\nSecond paragraph.',
            'assets/screenshots/10.png': '',
            'assets/screenshots/2.png': '',
            'assets/cover.webp': ''
        }
        cover, shots, video, description, progress_status = mod.find_media(api, example())
        self.assertTrue(cover.endswith('/assets/cover.webp'))
        self.assertTrue(shots[0].endswith('/assets/screenshots/2.png'))
        self.assertTrue(shots[1].endswith('/assets/screenshots/10.png'))
        self.assertEqual(video, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        self.assertIn('Game plot description.', description)
        self.assertEqual(progress_status, 'In-Progress')

    def test_media_metadata_is_in_project(self):
        api = FakeApi()
        api.asset_texts = {
            'assets/youtube.txt': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'assets/description.txt': 'Long game description'
        }
        project = mod.make_project(api, example(), {})
        self.assertEqual(project['youtube_url'], 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        self.assertEqual(project['game_description'], 'Long game description')
        self.assertEqual(project['release_tag'], '')

    def test_youtube_validation_rejects_unsafe_urls(self):
        bad = ['http://youtu.be/dQw4w9WgXcQ',
               'https://evil.example/?v=dQw4w9WgXcQ',
               'javascript:alert(1)',
               'https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ',
               'https://youtu.be/not-valid',
               'https://www.youtube.com/watch?v=']
        for url in bad:
            self.assertEqual(mod.valid_youtube_url(url), '', url)
        self.assertEqual(mod.valid_youtube_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=2s'),
                         'https://www.youtube.com/watch?v=dQw4w9WgXcQ')

    def test_newest_release_by_published_date(self):
        releases = [
            {'draft':False,'prerelease':False,'published_at':'2026-02-01T00:00:00Z','tag_name':'v1.0'},
            {'draft':False,'prerelease':True,'published_at':'2026-10-01T00:00:00Z','tag_name':'v1.1-beta'}]
        self.assertEqual(mod.recent_release(FakeApi(releases=releases), example())[2], 'v1.1-beta')

    def test_missing_repo_tree_has_safe_fallback(self):
        class EmptyTree(FakeApi):
            def get(self, path, params=None, optional=False):
                if '/git/trees/' in path: return None
                return super().get(path, params, optional)
        cover, screenshots, video, description, status = mod.find_media(EmptyTree(), example())
        self.assertEqual((cover, screenshots, video, description, status), ('', [], '', '', 'In-Progress'))

    def test_status_txt_paused_when_no_release(self):
        api = FakeApi()
        api.asset_texts = {'assets/status.txt': 'Paused\n'}
        project = mod.make_project(api, example(), {})
        self.assertEqual(project['status'], 'Paused')
        self.assertFalse(project['has_release'])
        self.assertEqual(project['release_tag'], '')

    def test_status_txt_in_progress_when_no_release(self):
        api = FakeApi()
        api.asset_texts = {'assets/status.txt': 'In-Progress\n'}
        project = mod.make_project(api, example(), {})
        self.assertEqual(project['status'], 'In-Progress')

    def test_missing_or_invalid_status_txt_defaults_to_in_progress(self):
        self.assertEqual(mod.make_project(FakeApi(), example(), {})['status'], 'In-Progress')
        for value in ('', 'Finished', 'Archived', 'In progress'):
            api = FakeApi()
            api.asset_texts = {'assets/status.txt': value}
            self.assertEqual(mod.make_project(api, example(), {})['status'], 'In-Progress')
        self.assertEqual(mod.parse_progress_status('pAuSeD\r\n'), 'Paused')

    def test_release_always_overrides_status_file(self):
        release = {'draft': False, 'prerelease': True, 'html_url': 'https://github.com/alice/translation/releases/tag/beta', 'tag_name': 'beta'}
        api = FakeApi(releases=[release])
        api.asset_texts = {'assets/status.txt': 'Paused'}
        project = mod.make_project(api, example(), {})
        self.assertEqual(project['status'], 'Released')
        self.assertTrue(project['has_release'])
        self.assertEqual(project['release_tag'], 'beta')
        self.assertEqual(project['release_url'], release['html_url'])

    def test_draft_does_not_count_as_release(self):
        draft = {'draft': True, 'prerelease': False, 'html_url': 'https://github.com/example/draft', 'tag_name': 'v1'}
        api = FakeApi(releases=[draft])
        api.asset_texts = {'assets/status.txt': 'Paused'}
        project = mod.make_project(api, example(), {})
        self.assertEqual(project['status'], 'Paused')
        self.assertFalse(project['has_release'])
        self.assertFalse(project['release_url'])

    def test_archived_repositories_use_release_and_status_rules(self):
        repo = example()
        repo['archived'] = True
        api = FakeApi()
        api.asset_texts = {'assets/status.txt': 'Paused'}
        self.assertEqual(mod.make_project(api, repo, {})['status'], 'Paused')

    def test_assets_directory_can_be_missing_entirely(self):
        class NoAssets(FakeApi):
            def get(self, path, params=None, optional=False):
                if '/git/trees/' in path:
                    return {'tree': [{'path': 'README.md', 'type': 'blob'}]}
                if '/contents/assets' in path:
                    return None  # GitHub Contents API optional 404
                return super().get(path, params, optional)
        repo = example(name='Dragon-Shadow-Spell_PS2', description='')
        repo['topics'] = []
        project = mod.make_project(NoAssets(), repo, {})
        self.assertEqual(project['title'], 'Dragon Shadow Spell')
        self.assertEqual(project['platform'], 'PS2')
        self.assertEqual(project['cover_url'], '')
        self.assertEqual(project['screenshots'], [])
        self.assertEqual(project['youtube_url'], '')
        self.assertEqual(project['game_description'], 'No game description provided.')
        self.assertEqual(project['status'], 'In-Progress')

    def test_empty_assets_directory_does_not_affect_metadata(self):
        class EmptyAssets(FakeApi):
            def get(self, path, params=None, optional=False):
                if '/git/trees/' in path:
                    return {'tree': [{'type': 'blob', 'path': 'README.md'},
                                     {'type': 'tree', 'path': 'assets'}]}
                return super().get(path, params, optional)
        repo = example(name='Ling_Rise_PS1_English-Translation', description='A classic RPG.', topics=[])
        project = mod.make_project(EmptyAssets(), repo, {})
        self.assertEqual(project['title'], 'Ling Rise')
        self.assertEqual(project['platform'], 'PS1')
        self.assertEqual(project['game_description'], 'A classic RPG.')
        self.assertEqual(project['cover_url'], '')

    def test_platform_detection_from_repo_name_without_topics(self):
        names = {
            'Lagnacure_Legends_PS1': ('Lagnacure Legends', 'PS1'),
            'PS2-Pride_of_the_Dragon_Peace-Translation': ('Pride of the Dragon Peace', 'PS2'),
            'DragonShadowSpellPS2': ('Dragon Shadow Spell', 'PS2'),
            'Ling-Rise-PSX': ('Ling Rise', 'PS1'),
            'PC-FX_Boundary_Gate': ('Boundary Gate', 'PC-FX'),
            'PCFX-Athena': ('Athena', 'PC-FX'),
            'Saturn-Dark-Savior': ('Dark Savior', 'Saturn'),
            'Some-Game-PSP-EN': ('Some Game', 'PSP'),
            'Saga_III_GBA_Fan_Translation': ('Saga III', 'GBA'),
            'translation-of-Bealphareth_PS1': ('Bealphareth', 'PS1'),
            'PS1-SACHOU_EIYUUDEN_ENG': ('Sachou Eiyuuden', 'PS1')
        }
        for name, (title, platform) in names.items():
            with self.subTest(repo=name):
                repo = example(name=name, description='', topics=[])
                self.assertEqual(mod.detect_platform(repo), platform)
                self.assertEqual(mod.display_title(repo, platform), title)

    def test_every_configured_platform_alias_and_clean_title(self):
        for platform, aliases in mod.PLATFORM_VARIANTS.items():
            for alias in aliases:
                with self.subTest(platform=platform, alias=alias):
                    repo = example(name='Sample-' + alias, description='', topics=[])
                    self.assertEqual(mod.detect_platform(repo), platform)
                    self.assertEqual(mod.display_title(repo, platform), 'Sample')

    def test_all_seventh_generation_home_consoles_and_common_aliases(self):
        variants = {
            'PS3': ['Sample-PS3', 'Sample-PlayStation3', 'Sample-PlayStation_3'],
            'Xbox 360': ['Sample-Xbox360', 'Sample-Xbox-360', 'Sample-XBox360', 'Sample-X360'],
            'Wii': ['Sample-Wii', 'Sample-Nintendo-Wii'],
            'PSP': ['Sample-PSP', 'Sample-PlayStation-Portable'],
            'NDS': ['Sample-NDS', 'Sample-NintendoDS', 'Sample-Nintendo-DSi'],
        }
        for platform, names in variants.items():
            for name in names:
                with self.subTest(name=name):
                    repo = example(name=name, description='', topics=[])
                    self.assertEqual(mod.detect_platform(repo), platform)
                    self.assertEqual(mod.display_title(repo, platform), 'Sample')

    def test_sixth_generation_consoles_and_handheld_aliases(self):
        variants = {
            'PS2': ['Sample-PS2', 'Sample-PlayStation2'],
            'GameCube': ['Sample-GCN', 'Sample-NGC', 'Sample-GameCube', 'Sample-Game_Cube'],
            'Xbox': ['Sample-Xbox', 'Sample-XBox', 'Sample-Original-Xbox'],
            'Dreamcast': ['Sample-Dreamcast', 'Sample-Sega-Dreamcast'],
            'GBA': ['Sample-GBA', 'Sample-GameBoyAdvance'],
            'N-Gage': ['Sample-N-Gage'],
        }
        for platform, names in variants.items():
            for name in names:
                with self.subTest(name=name):
                    self.assertEqual(mod.detect_platform(example(name=name, description='', topics=[])), platform)

    def test_classic_console_and_handheld_families(self):
        variants = {
            'PS1': ['Sample-PSX', 'Sample-PlayStation1'],
            'Saturn': ['Sample-Sega-Saturn'],
            'N64': ['Sample-Nintendo64'],
            '3DO': ['Sample-3DO'],
            'Jaguar': ['Sample-Atari-Jaguar'],
            'PC-FX': ['Sample-PCFX'],
            'GBC': ['Sample-GameBoyColor'],
            'SNES': ['Sample-SNES', 'Sample-Super-Famicom'],
            'Genesis': ['Sample-MegaDrive'],
            'Sega CD': ['Sample-Sega-CD'],
            '32X': ['Sample-Sega-32X'],
            'PC Engine CD': ['Sample-PC-Engine-CD'],
            'PC Engine': ['Sample-TurboGrafx16', 'Sample-PCE'],
            'Neo Geo CD': ['Sample-Neo-Geo-CD'],
            'Neo Geo': ['Sample-Neo-Geo'],
            'GB': ['Sample-GameBoy'],
            'Game Gear': ['Sample-GameGear'],
            'WonderSwan Color': ['Sample-WonderSwanColor'],
            'Neo Geo Pocket Color': ['Sample-Neo-Geo-Pocket-Color'],
            'NES': ['Sample-Famicom'],
            'Master System': ['Sample-Master-System'],
            'Atari 7800': ['Sample-Atari-7800'],
            'Atari 5200': ['Sample-Atari5200'],
            'Atari 2600': ['Sample-Atari2600'],
            'ColecoVision': ['Sample-ColecoVision'],
            'Intellivision': ['Sample-Intellivision'],
            'Vectrex': ['Sample-Vectrex'],
            'MSX2': ['Sample-MSX2'],
            'PC-98': ['Sample-PC98'],
        }
        for platform, names in variants.items():
            for name in names:
                with self.subTest(name=name):
                    self.assertEqual(mod.detect_platform(example(name=name, description='', topics=[])), platform)

    def test_platform_specificity_and_metadata_fallback(self):
        names = {
            'Example-Xbox-360': 'Xbox 360',
            'Example-Xbox': 'Xbox',
            'Example-Wii-U': 'Wii U',
            'Example-PC-FX': 'PC-FX',
            'Example-PC-Engine': 'PC Engine',
            'Example-PC-Engine-CD': 'PC Engine CD',
            'Example-Neo-Geo-Pocket-Color': 'Neo Geo Pocket Color',
            'Example-GameBoy-Color': 'GBC',
            'Example-GameBoy-Advance': 'GBA',
            'Example-PS4': 'PS4',
            'Example-Xbox-One': 'Xbox One',
            'Example-Xbox-Series-X': 'Xbox Series',
        }
        for name, platform in names.items():
            with self.subTest(name=name):
                self.assertEqual(mod.detect_platform(example(name=name, description='', topics=[])), platform)
        repo = example(name='Example', topics=['xbox-360'], description='for the Wii')
        self.assertEqual(mod.detect_platform(repo), 'Wii')  # Description precedes topics.
        repo['topics'] = []
        self.assertEqual(mod.detect_platform(repo), 'Wii')
        repo['name'] = 'Example-GameCube'
        self.assertEqual(mod.detect_platform(repo), 'GameCube')

    def test_platform_name_precedence_and_unknown(self):
        repo = example(name='Shadow_Rise_PS2', description='A PS1 project', topics=['psp'])
        self.assertEqual(mod.detect_platform(repo), 'PS2')
        repo = example(name='Shadow-Rise', description='A PS2 project', topics=['pc-fx'])
        self.assertEqual(mod.detect_platform(repo), 'PS2')  # Description precedes topics.
        repo = example(name='Shadow-Rise', description='For PlayStation 2', topics=[])
        self.assertEqual(mod.detect_platform(repo), 'PS2')
        repo = example(name='Shadow-Rise', description='', topics=[])
        self.assertEqual(mod.detect_platform(repo), 'Other')

    def test_multi_platform_detection_from_repository_description(self):
        repo = example(name='Boundary-Gate-English-Patch',
                       description='An English patch for the PCFX and PSX version of Boundary Gate',
                       topics=[])
        self.assertEqual(mod.display_title(repo, mod.detect_platform(repo)), 'Boundary Gate')
        self.assertEqual(mod.detect_platforms(repo), ['PC-FX', 'PS1'])
        self.assertEqual(mod.detect_platform(repo), 'PC-FX / PS1')
        project = mod.make_project(FakeApi(), repo, {})
        self.assertEqual(project['platform'], 'PC-FX / PS1')
        self.assertEqual(project['platforms'], ['PC-FX', 'PS1'])

    def test_multi_platform_description_precedes_topics(self):
        repo = example(name='Sample-Game-English-Patch',
                       description='Patch for both PSX and PC-FX', topics=['ps2'])
        self.assertEqual(mod.detect_platforms(repo), ['PS1', 'PC-FX'])
        repo['name'] = 'Sample-Game-PS3'
        self.assertEqual(mod.detect_platforms(repo), ['PS3'])

    def test_platforms_from_multiple_topics_when_no_description(self):
        repo = example(name='Sample-Game-English-Patch', description='No known consoles',
                       topics=['psx', 'pc-fx', 'psx', 'fan-translation'])
        self.assertEqual(mod.detect_platforms(repo), ['PS1', 'PC-FX'])

    def test_multiple_aliases_use_longest_match_and_deduplicate(self):
        self.assertEqual(mod.platforms_in_text('PC FX / PCFX, PSX (PlayStation 1)'),
                         ['PC-FX', 'PS1'])
        self.assertEqual(mod.platforms_in_text('Wii U and Xbox 360'), ['Wii U', 'Xbox 360'])
        self.assertEqual(mod.platforms_in_text('Just an English patch'), [])

    def test_unknown_platform_still_uses_other(self):
        project = mod.make_project(FakeApi(), example(name='Sample', description='', topics=[]), {})
        self.assertEqual(project['platform'], 'Other')
        self.assertEqual(project['platforms'], [])

    def test_explicit_platform_overrides_include_multiple_platforms(self):
        repo = example(name='Example', description='For PS2', topics=[])
        overrides = {'alice/Example': {'platforms': ['PC-FX', 'PS1', 'PS1']}}
        project = mod.make_project(FakeApi(), repo, overrides)
        self.assertEqual(project['platform'], 'PC-FX / PS1')
        self.assertEqual(project['platforms'], ['PC-FX', 'PS1'])
        overrides = {'alice/Example': {'platform': 'PS3 / Xbox 360'}}
        project = mod.make_project(FakeApi(), repo, overrides)
        self.assertEqual(project['platforms'], ['PS3', 'Xbox 360'])

    def test_published_release_with_missing_assets_is_released(self):
        class NoAssets(FakeApi):
            def get(self, path, params=None, optional=False):
                if '/git/trees/' in path:
                    return {'tree': [{'type': 'blob', 'path': 'README.md'}]}
                return super().get(path, params, optional)
        release = {'draft': False, 'tag_name': 'v1.0', 'published_at': '2026-10-30T00:00:00Z',
                   'html_url': 'https://github.com/alice/My-Game-PS1/releases/tag/v1.0'}
        repo = example(name='My-Game-PS1', description='', topics=[])
        project = mod.make_project(NoAssets(releases=[release]), repo, {})
        self.assertEqual(project['status'], 'Released')
        self.assertEqual(project['release_tag'], 'v1.0')
        self.assertEqual(project['release_url'], release['html_url'])

    def test_owner_required_without_other_sources(self):
        with self.assertRaises(ValueError):
            mod.discover_repos(FakeApi(), self.config)

    def test_exclude_forks_by_default(self):
        found = mod.discover_repos(FakeApi([example(fork=True)]), self.config, 'alice')
        self.assertEqual(found, [])

    def test_include_all_owner_repos(self):
        self.config['discovery']['include_all_owner_repos'] = True
        found = mod.discover_repos(FakeApi([example(name='misc', description='Not a translation', topics=[])]), self.config, 'alice')
        self.assertEqual(len(found), 1)

    def test_search_matches_even_without_repo_topic(self):
        self.config['discovery']['search_queries'] = ['topic:romhack ps2']
        found = mod.discover_repos(FakeApi([example(name='external', topics=[])]), self.config)
        self.assertEqual(len(found), 1)


if __name__ == '__main__':
    unittest.main()
