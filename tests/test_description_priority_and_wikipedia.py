"""Regression tests for Wikipedia and subscription-free game descriptions."""
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.game_links import (GameLinksClient, verified_wikipedia_game_url,
                                urls_from_igdb)
from scripts.build import make_project
from tests.test_igdb_integration import FakeApi, FakeIGDB, repo

ROOT = Path(__file__).resolve().parents[1]


class WikipediaAndDescriptionsTests(unittest.TestCase):
    def test_hikari_rejects_generic_downloadable_playstation_list(self):
        bad = "https://en.wikipedia.org/wiki/List_of_downloadable_PlayStation_games"
        self.assertEqual(verified_wikipedia_game_url(bad, "Hikari no Shima"), "")
        self.assertEqual(verified_wikipedia_game_url(bad,
            "Hikari no Shima: Seven Lithographs in Shining Island"), "")
        client = GameLinksClient(min_wiki_interval=0)
        with patch.object(client, '_wiki_page', return_value=('', '')):
            result = client.find('Hikari no Shima', ['PS1'],
                {'name': 'Hikari no Shima: Seven Lithographs in Shining Island',
                 'websites': [{'url':bad}]})
        self.assertEqual(result['wikipedia_url'], '')

    def test_igdb_moby_game_link_is_preserved_without_api_access(self):
        selected = urls_from_igdb({'websites': [
            {'url': 'http://www.mobygames.com/game/12345/'}]}, 'Sample Quest')
        self.assertEqual(selected['mobygames_url'],
                         'https://www.mobygames.com/game/12345/')

    def test_real_article_paths_accept_original_and_regional_title(self):
        self.assertTrue(verified_wikipedia_game_url(
            'https://en.wikipedia.org/wiki/Hikari_no_Shima', 'Hikari no Shima'))
        self.assertTrue(verified_wikipedia_game_url(
            'https://en.wikipedia.org/wiki/Venus_%26_Braves', 'Venus Braves'))
        self.assertTrue(verified_wikipedia_game_url(
            'https://en.wikipedia.org/wiki/Waga_Ryuu_o_Miyo:_Pride_of_the_Dragon_Peace',
            'Pride of the Dragon Peace'))
        self.assertTrue(verified_wikipedia_game_url(
            'https://en.wikipedia.org/wiki/JailBreaker', 'JailBreaker'))
        self.assertEqual(verified_wikipedia_game_url(
            'https://en.wikipedia.org/wiki/List_of_JailBreaker_games', 'JailBreaker'), '')
        self.assertEqual(verified_wikipedia_game_url(
            'https://en.wikipedia.org/wiki/PlayStation_games', 'Hikari no Shima'), '')
        self.assertEqual(verified_wikipedia_game_url(
            'https://en.wikipedia.org/wiki/Sample_Quest_II', 'Sample Quest'), '')

    def test_igdb_wiki_urls_filtered_by_title(self):
        selected = urls_from_igdb({"websites": [
            {"url": 'https://en.wikipedia.org/wiki/List_of_downloadable_PlayStation_games'},
            {"url": 'https://www.mobygames.com/game/1234'}]}, 'Hikari no Shima')
        self.assertEqual(selected['wikipedia_url'], '')
        self.assertTrue(selected['mobygames_url'])

    def test_bad_manual_override_is_removed(self):
        overrides = {'owner/Sample_Quest_PS2': {
            'wikipedia_url': 'https://en.wikipedia.org/wiki/List_of_PlayStation_2_games'}}
        result = make_project(FakeApi(), repo(), overrides)
        self.assertEqual(result['wikipedia_url'], '')

    def test_igdb_summary_preferred_to_repository_description(self):
        result = make_project(FakeApi(), repo(), {}, FakeIGDB())
        self.assertEqual(result['game_description'], 'IGDB summary.')
        self.assertEqual(result['description_source'], 'IGDB')

    def test_moby_link_does_not_supply_a_description(self):
        class Links:
            def find(self, *args):
                return {'mobygames_url':'https://www.mobygames.com/game/123/',
                        'wikipedia_url':''}
        result = make_project(FakeApi(), repo(), {}, FakeIGDB(), links=Links())
        self.assertEqual(result['game_description'], 'IGDB summary.')
        self.assertEqual(result['description_source'], 'IGDB')
        self.assertEqual(result['mobygames_url'], 'https://www.mobygames.com/game/123/')

    def test_no_moby_description_even_if_link_provider_supplies_one(self):
        class Links:
            def find(self, *args):
                return {'mobygames_url':'https://www.mobygames.com/game/123/',
                        'wikipedia_url':'', 'mobygames_description':'Should not be copied.'}
        result = make_project(FakeApi(), repo(), {}, FakeIGDB(), links=Links())
        self.assertEqual(result['game_description'], 'IGDB summary.')
        self.assertEqual(result['description_source'], 'IGDB')

    def test_manual_and_repo_descriptions_win(self):
        class Links:
            def find(self, *args):
                return {'mobygames_url':'https://www.mobygames.com/game/123/',
                        'wikipedia_url':''}
        api = FakeApi()
        api.paths = ['assets/description.txt']
        api.get = lambda path, params=None, optional=False: (
            {'tree':[{'type':'blob','path':'assets/description.txt'}]}
            if '/git/trees/' in path else
            {'content':'TG9jYWwgZGVzY3JpcHRpb24=', 'encoding':'base64'}
            if '/contents/' in path else [] if path.endswith('/releases') else None)
        result = make_project(api, repo(), {}, FakeIGDB(), links=Links())
        self.assertEqual(result['game_description'], 'Local description')
        self.assertEqual(result['description_source_url'], '')
        result = make_project(FakeApi(), repo(), {
            'owner/Sample_Quest_PS2': {'game_description': 'Manually curated'}},
            FakeIGDB(), links=Links())
        self.assertEqual(result['game_description'], 'Manually curated')
        self.assertEqual(result['description_source_url'], '')

    def test_api_secrets_and_endpoints_not_in_build(self):
        for name in ('scripts/build.py', 'scripts/game_links.py',
                     '.github/workflows/pages.yml', 'README.md'):
            with self.subTest(file=name):
                content = (ROOT / name).read_text(encoding='utf-8')
                self.assertNotIn('MOBYGAMES_API_KEY', content)
                self.assertNotIn('api.mobygames.com', content)
        client = GameLinksClient(min_wiki_interval=0)
        self.assertFalse(hasattr(client, '_moby_api'))
        self.assertFalse(hasattr(client, '_moby_description'))
        self.assertFalse(hasattr(client, 'mobygames_key'))

    def test_no_mobygames_requests_when_link_is_igdb_supplied(self):
        client = GameLinksClient(min_wiki_interval=0)
        with patch.object(client, '_wiki_page', return_value=('', '')):
            got = client.find('Sample Quest', ['PS2'], {'name':'Sample Quest',
                'websites':[{'url':'https://www.mobygames.com/game/12345/'}]})
        self.assertEqual(got['mobygames_url'], 'https://www.mobygames.com/game/12345/')
        self.assertNotIn('mobygames_description', got)

    def test_mobygames_link_still_appears_in_browser(self):
        js = (ROOT / 'site/app.js').read_text(encoding='utf8')
        self.assertIn('MobyGames ↗', js)
        self.assertIn('Description source ↗', js)
        self.assertNotIn('Data by MobyGames.com', js)


if __name__ == '__main__':
    unittest.main()
