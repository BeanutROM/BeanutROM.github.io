"""Wikipedia description priority, attribution, and safe build-time fallbacks."""
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from scripts.build import make_project
from scripts.game_links import GameLinksClient
from tests.test_igdb_integration import FakeApi, FakeIGDB, repo


ARTICLE = "https://en.wikipedia.org/wiki/Sample_Quest_(video_game)"
INTRO = "Sample Quest is a role-playing video game released for the PlayStation 2 in 2004."


def article_record(title="Sample Quest (video game)", intro=INTRO, **extra):
    return {"query": {"pages": {"12": {"pageid": 12, "ns": 0,
            "title": title, "extract": intro, "pageprops": {}, **extra}}}}


class Links:
    def __init__(self, url=ARTICLE, intro=INTRO, fail=False):
        self.url = url
        self.intro = intro
        self.fail = fail
        self.requested = []

    def find(self, *args):
        return {"wikipedia_url": self.url, "mobygames_url": ""}

    def wikipedia_description(self, url, titles, platforms):
        self.requested.append((url, titles, platforms))
        if self.fail:
            raise RuntimeError('simulated outage')
        return self.intro


class WikipediaDescriptionTests(unittest.TestCase):
    def test_wikipedia_overrides_igdb_with_attribution(self):
        links = Links()
        project = make_project(FakeApi(), repo(), {}, FakeIGDB(), links=links)
        self.assertEqual(project['game_description'], INTRO)
        self.assertEqual(project['description_source'], 'Wikipedia')
        self.assertEqual(project['description_source_url'], ARTICLE)
        self.assertEqual(links.requested[0][2], ['PS2'])
        self.assertEqual(project['igdb_url'], 'https://www.igdb.com/games/sample-quest')

    def test_wikipedia_without_igdb_also_works(self):
        project = make_project(FakeApi(), repo(), {}, links=Links())
        self.assertEqual(project['description_source'], 'Wikipedia')
        self.assertEqual(project['game_description'], INTRO)

    def test_no_valid_article_falls_back_to_igdb(self):
        links = Links(url='https://en.wikipedia.org/wiki/List_of_downloadable_PlayStation_games')
        project = make_project(FakeApi(), repo(), {}, FakeIGDB(), links=links)
        self.assertEqual(project['game_description'], 'IGDB summary.')
        self.assertEqual(project['description_source'], 'IGDB')
        self.assertEqual(links.requested, [])

    def test_api_failure_or_empty_intro_falls_back(self):
        for links in (Links(fail=True), Links(intro='')):
            with self.subTest(links=links):
                with patch('sys.stderr'):
                    project = make_project(FakeApi(), repo(), {}, FakeIGDB(), links=links)
                self.assertEqual(project['game_description'], 'IGDB summary.')
                self.assertEqual(project['description_source_url'],
                                 'https://www.igdb.com/games/sample-quest')

    def test_local_and_manual_descriptions_take_priority(self):
        links = Links()
        overrides = {repo()['full_name']: {'game_description':'Manually written summary.'}}
        project = make_project(FakeApi(), repo(), overrides, FakeIGDB(), links=links)
        self.assertEqual(project['game_description'], 'Manually written summary.')
        self.assertEqual(links.requested, [])
        self.assertEqual(project['description_source'], '')
        local = FakeApi(['assets/description.txt'])
        # The existing test's API fixture reads local description via a base64 payload.
        local.get = lambda path, params=None, optional=False: (
            {'tree': [{'type':'blob','path':'assets/description.txt'}]}
            if '/git/trees/' in path else
            {'content':'TG9jYWwgZGVzY3JpcHRpb24=', 'encoding':'base64'}
            if '/contents/' in path else [] if path.endswith('/releases') else None)
        project = make_project(local, repo(), {}, FakeIGDB(), links=links)
        self.assertEqual(project['game_description'], 'Local description')
        self.assertEqual(links.requested, [])

    def test_manual_wikipedia_link_can_supply_description(self):
        links = Links(url='')
        project = make_project(FakeApi(), repo(), {
            repo()['full_name']: {'wikipedia_url': ARTICLE}}, FakeIGDB(), links=links)
        self.assertEqual(project['game_description'], INTRO)
        self.assertEqual(project['wikipedia_url'], ARTICLE)
        self.assertEqual(project['description_source_url'], ARTICLE)

    def test_client_fetches_public_api_plain_text_and_rechecks_article(self):
        client = GameLinksClient(min_wiki_interval=0)
        with patch.object(client, '_get', return_value=article_record()) as get:
            text = client.wikipedia_description(ARTICLE, ['Sample Quest'], ['PS2'])
        self.assertEqual(text, INTRO)
        url = get.call_args.args[0]
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params['prop'], ['extracts|pageprops'])
        self.assertEqual(params['explaintext'], ['1'])
        self.assertEqual(params['exintro'], ['1'])
        self.assertEqual(params['exchars'], ['1100'])
        self.assertEqual(params['titles'], ['Sample Quest (video game)'])

    def test_client_rejects_non_game_article_and_disambiguation(self):
        client = GameLinksClient(min_wiki_interval=0)
        non_game = 'Sample Quest is a fictional character appearing in several magazines.'
        bad_records = (
            article_record(intro=non_game),
            article_record(title='Different Quest (video game)'),
            article_record(pageprops={'disambiguation': ''}),
            article_record(intro=INTRO.replace('PlayStation 2', 'Xbox 360')),
            article_record(intro=''),
            {'query':{'pages':{'-1':{'missing':'', 'title':'Sample Quest'}}}},
        )
        for record in bad_records:
            with self.subTest(record=record):
                with patch.object(client, '_get', return_value=record):
                    self.assertEqual(client.wikipedia_description(ARTICLE, ['Sample Quest'], ['PS2']), '')

    def test_client_never_fetches_a_list_page(self):
        client = GameLinksClient(min_wiki_interval=0)
        with patch.object(client, '_get') as get:
            self.assertEqual(client.wikipedia_description(
                'https://en.wikipedia.org/wiki/List_of_downloadable_PlayStation_games',
                ['Hikari no Shima'], ['PS1']), '')
        get.assert_not_called()

    def test_site_displays_wikipedia_credit_and_license(self):
        js = (Path(__file__).resolve().parents[1] / 'site/app.js').read_text()
        self.assertIn('Wikipedia contributors', js)
        self.assertIn('creativecommons.org/licenses/by-sa/4.0/', js)
        self.assertIn('shortened for display', js)
        self.assertIn('description_source', js)


if __name__ == '__main__':
    unittest.main()
