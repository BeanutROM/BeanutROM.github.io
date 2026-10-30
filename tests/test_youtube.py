"""YouTube channel indexing and title association: no external calls."""
import json
import unittest
from unittest.mock import patch

from scripts.youtube import YouTubeChannel, associate_videos, parse_channel, phrase_score

CID = 'UC' + 'A' * 22
VID1, VID2, VID3 = 'abcdefghijk', '123456789AB', 'zxCVBNMasdf'


class YouTubeTests(unittest.TestCase):
    def test_channel_id_handle_and_urls(self):
        self.assertEqual(parse_channel(CID), ('id', CID))
        self.assertEqual(parse_channel('https://www.youtube.com/channel/' + CID), ('id', CID))
        self.assertEqual(parse_channel('@ExampleChannel'), ('handle', '@ExampleChannel'))
        self.assertEqual(parse_channel('https://youtube.com/@ExampleChannel/videos'), ('handle', '@ExampleChannel'))
        self.assertIsNone(parse_channel('https://evil.com/channel/' + CID))
        self.assertIsNone(parse_channel('not-a-channel'))

    def test_title_matching_and_sequel_protection(self):
        self.assertGreater(phrase_score('Venus Braves', 'Venus & Braves (PS2) English Patch Gameplay'), 0)
        self.assertGreater(phrase_score('Pride of the Dragon Peace', 'Waga Ryuu o Miyo: Pride of the Dragon Peace'), 0)
        self.assertGreater(phrase_score('Hikari no Shima', 'Hikari no Shima: Seven Lithographs in Shining Island'), 0)
        self.assertEqual(phrase_score('Sample Quest', 'Sample Quest II Trailer'), 0)
        self.assertEqual(phrase_score('Sample Quest', 'Sample Quest 2 Gameplay'), 0)
        self.assertEqual(phrase_score('Go', 'Go play games'), 0)
        self.assertEqual(phrase_score('Sample Quest', 'Unrelated Story'), 0)

    def test_distinctive_single_word_and_joined_titles(self):
        self.assertGreater(phrase_score('Tenerezza', 'Tenerezza XBox English Translation'), 0)
        self.assertGreater(phrase_score('JailBreaker', 'JailBreaker PSX English Translation'), 0)
        self.assertGreater(phrase_score('Jail Breaker', 'JailBreaker PSX English Translation'), 0)
        self.assertGreater(phrase_score('JailBreaker', 'Jail Breaker PSX English Translation'), 0)
        self.assertEqual(phrase_score('Athena', 'Athena gameplay PS1'), 0)
        self.assertEqual(phrase_score('Go', 'Go gameplay PS1'), 0)
        self.assertEqual(phrase_score('Tenerezza', 'Tenerezza II Trailer'), 0)
        self.assertEqual(phrase_score('JailBreaker', 'JailBreaker 2 Trailer'), 0)
        self.assertEqual(phrase_score('Tenerezza', 'TenerezzaLike XBox English Translation'), 0)

    def test_diagnostic_examples_both_associate(self):
        projects = [
            {'repo': 'BeanutROM/XBox-Tenerezza-English-Patch', 'title': 'Tenerezza'},
            {'repo': 'BeanutROM/PSX-JailBreaker-English-Patch',
             'title': 'Jail Breaker', 'youtube_match_titles': ['JailBreaker']},
        ]
        diagnostic = {}
        associate_videos(projects, [
            {'id': 'Src2whmWGrk', 'title': 'JailBreaker PSX English Translation'},
            {'id': 'GnMKq9tcRnU', 'title': 'Tenerezza XBox English Translation'},
        ], diagnostics=diagnostic)
        self.assertEqual([v['outcome'] for v in diagnostic['videos']], ['matched', 'matched'])
        self.assertFalse(any(p['matching_limited'] for p in diagnostic['projects']))
        self.assertEqual(len(projects[0]['youtube_videos']), 1)
        self.assertEqual(len(projects[1]['youtube_videos']), 1)

    def test_video_association_preserves_manual_and_rejects_ambiguous(self):
        a = {'title': 'Venus Braves', 'youtube_url': 'https://www.youtube.com/watch?v=' + VID1}
        b = {'title': 'Hikari no Shima', 'youtube_url': ''}
        projects = [a, b]
        associate_videos(projects, [
            {'id': VID1, 'title': 'Venus & Braves PS2'},
            {'id': VID2, 'title': 'Venus & Braves PS2 English Patch'},
            {'id': VID3, 'title': 'Hikari no Shima: Seven Lithographs in Shining Island'},
        ])
        self.assertEqual([v['url'].rsplit('=', 1)[-1] for v in a['youtube_videos']], [VID2])
        self.assertEqual([v['url'].rsplit('=', 1)[-1] for v in b['youtube_videos']], [VID3])
        self.assertIn(VID1, a['youtube_url'])
        self.assertNotIn('igdb_title', a)

    def test_ambiguous_matching_skipped(self):
        projects = [{'title':'Sample Quest'}, {'title':'Sample Quest'}]
        associate_videos(projects, [{'id': VID1, 'title':'Sample Quest Gameplay'}])
        self.assertEqual(projects[0]['youtube_videos'], [])
        self.assertEqual(projects[1]['youtube_videos'], [])

    def test_rss_feed_without_key(self):
        xml = f'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId>{VID1}</yt:videoId><title>Venus &amp; Braves</title></entry></feed>'''
        client = YouTubeChannel(CID)
        with patch.object(client, '_request', return_value=xml.encode()) as req:
            self.assertEqual(client.videos(), [{'id': VID1, 'title': 'Venus & Braves'}])
            self.assertIn('channel_id', req.call_args.args[1])
        with self.assertRaisesRegex(RuntimeError, 'YOUTUBE_API_KEY'):
            YouTubeChannel('@ExampleChannel').videos()

    def test_api_key_fetches_paginated_uploads(self):
        client = YouTubeChannel('@ExampleChannel', 'super-secret-key')
        pages = [
            {'items': [{'contentDetails': {'relatedPlaylists': {'uploads':'UUtest'}}}]},
            {'items': [{'snippet': {'resourceId': {'videoId': VID1}, 'title':'Venus Braves'}}], 'nextPageToken':'next'},
            {'items': [{'snippet': {'resourceId': {'videoId': VID2}, 'title':'Hikari no Shima'}}]},
        ]
        with patch.object(client, '_json', side_effect=pages) as req:
            self.assertEqual(len(client.videos()), 2)
            self.assertEqual(req.call_args_list[0].kwargs['forHandle'], '@ExampleChannel')
            self.assertEqual(req.call_args_list[1].kwargs['playlistId'], 'UUtest')
            self.assertEqual(req.call_args_list[2].kwargs['pageToken'], 'next')

    def test_api_errors_do_not_expose_key(self):
        from urllib.error import HTTPError
        from io import BytesIO
        client = YouTubeChannel(CID, 'my-super-secret')
        failure = HTTPError('https://example.invalid', 403, 'Forbidden', {}, BytesIO(b'my-super-secret'))
        with patch('scripts.youtube.urlopen', side_effect=failure):
            with self.assertRaises(RuntimeError) as raised:
                client.videos()
        self.assertNotIn('my-super-secret', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
