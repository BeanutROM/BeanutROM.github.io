"""External reference tests use simulated API responses; no credentials/network."""
import unittest
from unittest.mock import patch
from scripts.game_links import (verified_url, urls_from_igdb, pick_wikipedia,
                                match_wikipedia_title, wikidata_moby_url,
                                GameLinksClient)
from scripts.build import make_project
from tests.test_igdb_integration import FakeApi, FakeIGDB, repo


class GameLinksTests(unittest.TestCase):
    def test_trusted_game_urls_only(self):
        self.assertEqual(verified_url('https://en.wikipedia.org/wiki/Venus_%26_Braves', 'wikipedia'),
                         'https://en.wikipedia.org/wiki/Venus_%26_Braves')
        self.assertTrue(verified_url('https://www.mobygames.com/game/1234/title/', 'mobygames'))
        self.assertTrue(verified_url('https://www.mobygames.com/game/game-title', 'mobygames'))
        for url in ('https://bad.mobygames.com/game/123', 'https://www.mobygames.com/search/?q=Game',
                    'javascript:alert(1)', 'http://en.wikipedia.org/wiki/Sample',
                    'https://en.wikipedia.org.evil.tld/wiki/Fake'):
            with self.subTest(url=url):
                self.assertEqual(verified_url(url, 'wikipedia'), '')
                self.assertEqual(verified_url(url, 'mobygames'), '')

    def test_igdb_websites_are_accepted_by_host_not_enum(self):
        result = urls_from_igdb({'websites':[
            {'url':'https://en.wikipedia.org/wiki/Hikari_no_Shima'},
            {'url':'https://www.mobygames.com/game/1234/'},
            {'url':'https://evil.example.org/wiki/Bad'}]})
        self.assertEqual(result['mobygames_url'], 'https://www.mobygames.com/game/1234/')
        self.assertEqual(result['wikipedia_url'], 'https://en.wikipedia.org/wiki/Hikari_no_Shima')

    def test_wikipedia_short_title_and_connecting_ampersand(self):
        self.assertGreaterEqual(match_wikipedia_title('Hikari no Shima', 'Hikari no Shima: Seven Lithographs in Shining Island'), .9)
        self.assertGreaterEqual(match_wikipedia_title('Venus Braves', 'Venus & Braves (video game)'), .9)
        self.assertEqual(match_wikipedia_title('Sample Quest', 'Sample Quest 2'), 0)
        entry = {'pageid': 42, 'title':'Venus & Braves (video game)'}
        self.assertEqual(pick_wikipedia([entry], 'Venus Braves'), entry)
        self.assertIsNone(pick_wikipedia([entry, {'pageid':50,'title':'Venus and Braves'}], 'Venus Braves'))

    def test_moby_game_id_and_old_slug(self):
        current = {'claims': {'P11688': [{'mainsnak': {'datavalue': {'value':'42121'}}}]}}
        old = {'claims': {'P1933': [{'mainsnak': {'datavalue': {'value':'example-game'}}}]}}
        self.assertEqual(wikidata_moby_url(current), 'https://www.mobygames.com/game/42121/')
        self.assertEqual(wikidata_moby_url(old), 'https://www.mobygames.com/game/example-game')
        self.assertEqual(wikidata_moby_url({'claims': {'P11688':[{'mainsnak':{'datavalue':{'value':'../evil'}}}]}}), '')

    def test_build_uses_link_lookup_on_repos_with_cover_and_description(self):
        class Links:
            def __init__(self): self.requests = []
            def find(self, title, platforms, igdb_game):
                self.requests.append((title, platforms, igdb_game))
                return {'wikipedia_url':'https://en.wikipedia.org/wiki/Sample_Quest',
                        'mobygames_url':'https://www.mobygames.com/game/123/'}
        links = Links()
        overrides = {'owner/Sample_Quest_PS2':{'game_description':'Override description'}}
        result = make_project(FakeApi(['assets/cover.png']), repo(), overrides, FakeIGDB(), links=links)
        self.assertEqual(result['wikipedia_url'], 'https://en.wikipedia.org/wiki/Sample_Quest')
        self.assertEqual(result['mobygames_url'], 'https://www.mobygames.com/game/123/')
        self.assertEqual(links.requests[0][0], 'Sample Quest')

    def test_link_service_failures_do_not_cancel_project(self):
        class BrokenLinks:
            def find(self, *args): raise RuntimeError('simulated error')
        with patch('sys.stderr'):
            result = make_project(FakeApi(), repo(), {}, links=BrokenLinks())
        self.assertEqual(result['wikipedia_url'], '')
        self.assertEqual(result['mobygames_url'], '')

    def test_manual_links_and_insecure_override(self):
        overrides = {'owner/Sample_Quest_PS2': {
            'mobygames_url':'https://www.mobygames.com/game/123/',
            'wikipedia_url':'https://en.wikipedia.org/wiki/Sample_Quest'}}
        game = make_project(FakeApi(), repo(), overrides)
        self.assertIn('mobygames.com/game/123', game['mobygames_url'])
        self.assertIn('wikipedia.org/wiki/', game['wikipedia_url'])
        overrides['owner/Sample_Quest_PS2']['wikipedia_url']='https://evil.test/'
        self.assertEqual(make_project(FakeApi(), repo(), overrides)['wikipedia_url'], '')

    def test_igdb_wiki_and_wikidata_moby_without_third_party_api_key(self):
        client = GameLinksClient(min_wiki_interval=0)
        qid = 'Q123'
        fake_data = {
            'query': {'pages': {'1': {'pageprops': {'wikibase_item': qid}}}}}
        def fake_get(url, service):
            if 'Special:EntityData' in url:
                return {'entities': {qid: {'claims': {'P11688': [
                    {'mainsnak': {'datavalue': {'value': 12345}}}]}}}}
            return fake_data
        with patch.object(client, '_get', side_effect=fake_get):
            got = client.find('Example Game', ['PS1'], {
                'name':'Example Game', 'websites':[{'url':'https://en.wikipedia.org/wiki/Example_Game'}]})
        self.assertEqual(got, {'wikipedia_url':'https://en.wikipedia.org/wiki/Example_Game',
                               'mobygames_url':'https://www.mobygames.com/game/12345/'})

    def test_wikipedia_api_rejects_wrong_platform_or_unrelated_article(self):
        client = GameLinksClient(min_wiki_interval=0)
        def fake_get(url, service):
            if 'list=search' in url:
                return {'query': {'search': [{'title': 'Sample Quest (video game)', 'pageid': 123}]}}
            return {'query': {'pages': {'123': {
                'title':'Sample Quest (video game)',
                'extract': 'Sample Quest is a 2005 action video game released for PlayStation 2.',
                'pageprops': {'wikibase_item': 'Q321'}}}}}
        with patch.object(client, '_get', side_effect=fake_get):
            self.assertEqual(client._wiki_page('Sample Quest', ['PS2'])[1], 'Q321')
            self.assertEqual(client._wiki_page('Sample Quest', ['PS3']), ('', ''))

    def test_wikipedia_api_rejects_unrelated_title(self):
        client = GameLinksClient(min_wiki_interval=0)
        with patch.object(client, '_get', return_value={'query': {'search': [
                {'title':'Sample Quest II', 'pageid': 12}]}}):
            self.assertEqual(client._wiki_page('Sample Quest', ['PS2']), ('', ''))

    def test_js_details_shows_only_available_links(self):
        from pathlib import Path
        js = (Path(__file__).resolve().parents[1] / 'site/app.js').read_text()
        self.assertIn('p.mobygames_url', js)
        self.assertIn('p.wikipedia_url', js)
        self.assertIn('MobyGames ↗', js)
        self.assertIn('Wikipedia ↗', js)
        self.assertIn('mobygamesUrl ? ', js)
        self.assertIn('wikipediaUrl ? ', js)


if __name__ == '__main__':
    unittest.main()
