"""IGDB tests: API responses are mocked; no credentials or live calls needed."""
import json
import unittest
from unittest.mock import patch
from scripts.igdb import IGDBClient, choose_game, cover_image, game_page, platform_matches, fallback_queries


GAME = {
    'id': 1234, 'name': 'Sample Quest', 'slug': 'sample-quest',
    'cover': {'image_id': 'co1abc'},
    'platforms': [{'name': 'PlayStation 2', 'abbreviation': 'PS2'}],
    'summary': 'A quest for a lost city.'
}


class Response:
    def __init__(self, obj):
        self.data = json.dumps(obj).encode()
    def read(self, size=-1):
        return self.data if size < 0 else self.data[:size]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class IGDBTests(unittest.TestCase):
    def test_exact_match_and_correct_platform(self):
        self.assertEqual(choose_game([GAME], 'Sample Quest', 'PS2'), GAME)
        self.assertIsNone(choose_game([GAME], 'Sample Quest', 'PS3'))
        self.assertIsNone(choose_game([GAME], 'Completely Different', 'PS2'))

    def test_seventh_generation_platforms(self):
        for label, name in [('PS3', 'PlayStation 3'), ('Xbox 360', 'Xbox 360'),
                            ('Wii', 'Wii'), ('GameCube', 'Nintendo GameCube'),
                            ('Xbox', 'Xbox')]:
            with self.subTest(label=label):
                self.assertTrue(platform_matches(label, [{'name': name}]))
        self.assertFalse(platform_matches('Xbox', [{'name': 'Xbox 360'}]))

    def test_no_platform_info_does_not_invent_match(self):
        self.assertIsNone(platform_matches('PS2', []))
        self.assertIsNone(platform_matches('Other', GAME['platforms']))
        self.assertEqual(choose_game([{**GAME, 'platforms': []}], 'Sample Quest', 'PS2')['id'], 1234)

    def test_cover_url_and_slug_validation(self):
        self.assertEqual(cover_image(GAME), 'https://images.igdb.com/igdb/image/upload/t_cover_big_2x/co1abc.jpg')
        self.assertEqual(game_page(GAME), 'https://www.igdb.com/games/sample-quest')
        self.assertEqual(cover_image({'cover':{'image_id':'../evil'}}), '')
        self.assertEqual(game_page({'slug': 'bad/path'}), '')

    def test_oauth_credentials_not_sent_to_igdb_or_site(self):
        requests = []
        def fake_open(request, timeout):
            requests.append(request)
            if 'oauth2/token' in request.full_url:
                return Response({'access_token': 'access-token-do-not-publish'})
            return Response([GAME])
        with patch('scripts.igdb.urlopen', side_effect=fake_open):
            client = IGDBClient('test-client-id', 'test-secret', min_interval=0)
            actual = client.get_game('Sample Quest', 'PS2')
            self.assertEqual(actual, GAME)
            self.assertEqual(len(requests), 2)
            self.assertIn(b'test-secret', requests[0].data)
            self.assertNotIn(b'test-secret', requests[1].data)
            self.assertNotIn('test-secret', requests[1].full_url)
            self.assertEqual(requests[1].get_header('Authorization'), 'Bearer access-token-do-not-publish')
            self.assertIn('search "Sample Quest"', requests[1].data.decode())
            self.assertEqual(client.get_game('Sample Quest', 'PS2'), GAME)
            self.assertEqual(len(requests), 2)  # cache avoids extra API requests

    def test_multiple_platforms_igdb_matches_either_console(self):
        self.assertTrue(platform_matches(['PC-FX', 'PS1'], [{'name': 'PlayStation'}]))
        self.assertTrue(platform_matches(['PC-FX', 'PS1'], [{'name': 'PC-FX'}]))
        self.assertFalse(platform_matches(['PC-FX', 'PS1'], [{'name': 'PlayStation 2'}]))
        match = {'name':'Boundary Gate', 'cover': {'image_id': 'co123'},
                 'platforms': [{'name':'PlayStation'}]}
        self.assertEqual(choose_game([match], 'Boundary Gate', ['PC-FX', 'PS1']), match)

    def test_partial_title_with_clear_subtitle(self):
        result = {**GAME, 'name': 'Hikari no Shima: Seven Lithographs in Shining Island'}
        self.assertEqual(choose_game([result], 'Hikari no Shima', 'PS2'), result)
        self.assertEqual(choose_game([result], 'Hikari no Shima', 'PS3'), None)

    def test_regional_prefix_then_full_game_title(self):
        result = {**GAME, 'name': 'Waga Ryuu o Miyo: Pride of the Dragon Peace'}
        self.assertEqual(choose_game([result], 'Pride of the Dragon Peace', 'PS2'), result)
        self.assertIsNone(choose_game([result], 'Pride of the Dragon Peace', 'PS3'))
        other = {**GAME, 'name': 'Unrelated Game: Pride of the Dragon Peace', 'id': 777}
        self.assertIsNone(choose_game([result, other], 'Pride of the Dragon Peace', 'PS2'))
        self.assertIsNone(choose_game([{**GAME, 'name': 'Waga Ryuu o Miyo Pride of the Dragon Peace'}],
                                       'Pride of the Dragon Peace', 'PS2'))

    def test_client_igdb_fallback_for_prefixed_official_title(self):
        result = {**GAME, 'name': 'Waga Ryuu o Miyo: Pride of the Dragon Peace'}
        client = IGDBClient('a', 'b')
        with patch.object(client, '_query', side_effect=[[], [result]]) as query:
            self.assertEqual(client.get_game('Pride of the Dragon Peace', 'PS2'), result)
            self.assertIn('search "pride"', query.call_args.args[0])

    def test_ampersand_and_missing_conjunction(self):
        result = {**GAME, 'name': 'Venus & Braves'}
        self.assertEqual(choose_game([result], 'Venus Braves', 'PS2'), result)
        self.assertEqual(choose_game([result], 'Venus and Braves', 'PS2'), result)
        self.assertEqual(choose_game([result], 'Venus Braves', 'PS1'), None)

    def test_do_not_guess_unmarked_partial_or_sequel(self):
        results = [{**GAME, 'name': 'Sample Quest II'},
                   {**GAME, 'name': 'Sample Quest Remastered'},
                   {**GAME, 'name': 'Sample Quest Prologue'}]
        self.assertIsNone(choose_game(results, 'Sample Quest', 'PS2'))

    def test_exact_name_beats_partial_subtitle(self):
        exact = {**GAME, 'id': 1, 'name': 'Hikari no Shima'}
        subtitle = {**GAME, 'id': 2, 'name': 'Hikari no Shima: Another World'}
        self.assertEqual(choose_game([subtitle, exact], 'Hikari no Shima', 'PS2'), exact)

    def test_ambiguous_subtitles_are_not_guessed(self):
        a = {**GAME, 'id': 1, 'name': 'Hikari no Shima: First World'}
        b = {**GAME, 'id': 2, 'name': 'Hikari no Shima: Second World'}
        self.assertIsNone(choose_game([a, b], 'Hikari no Shima', 'PS2'))

    def test_igdb_alternative_name_field(self):
        item = {**GAME, 'name': 'Alternate Official Title',
                'alternative_names': [{'name': 'Venus & Braves'}]}
        self.assertEqual(choose_game([item], 'Venus Braves', 'PS2'), item)
        self.assertEqual(choose_game([{**item,'alternative_names':None}], 'Venus Braves', 'PS2'), None)

    def test_client_retries_shorter_search_if_first_does_not_match(self):
        game = {**GAME, 'name': 'Venus & Braves'}
        client = IGDBClient('a', 'b')
        with patch.object(client, '_query', side_effect=[[], [game]]) as query:
            self.assertEqual(client.get_game('Venus Braves', 'PS2'), game)
            bodies = [c.args[0] for c in query.call_args_list]
            self.assertEqual(len(bodies), 2)
            self.assertIn('search "Venus Braves"', bodies[0])
            self.assertIn('search "venus & braves"', bodies[1])

    def test_client_retries_anchor_for_extended_title(self):
        game = {**GAME, 'name': 'Hikari no Shima: Seven Lithographs in Shining Island'}
        client = IGDBClient('a', 'b')
        with patch.object(client, '_query', side_effect=[[], [game]]) as query:
            self.assertEqual(client.get_game('Hikari no Shima', 'PS2'), game)
            self.assertIn('search "hikari"', query.call_args.args[0])

    def test_client_returns_none_when_fallbacks_still_fail(self):
        client = IGDBClient('a', 'b')
        with patch.object(client, '_query', return_value=[{**GAME,'name':'Unrelated'}]) as query:
            self.assertIsNone(client.get_game('Venus Braves', 'PS2'))
            self.assertLessEqual(query.call_count, 3)

    def test_explicit_id_override(self):
        client = IGDBClient('a', 'b')
        with patch.object(client, '_query', return_value=[GAME]) as query:
            self.assertEqual(client.get_game('Unknown Name', 'Other', 1234), GAME)
            self.assertIn('where id = 1234', query.call_args.args[0])
            self.assertIsNone(client.get_game('Unknown Name', 'Other', 'bad'))
            self.assertEqual(query.call_count, 1)

    def test_query_escapes_quotes_and_delimiters(self):
        client = IGDBClient('a', 'b')
        with patch.object(client, '_query', return_value=[]) as query:
            client.get_game('Sample "Quest"; where id=1', 'Other')
            self.assertIn('search "Sample \\"Quest\\"; where id=1";', query.call_args_list[0].args[0])


if __name__ == '__main__':
    unittest.main()
