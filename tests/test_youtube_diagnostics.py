"""YouTube build diagnostics and actionable failure logs."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from io import BytesIO
from urllib.error import HTTPError

from scripts.build import index_youtube
from scripts.youtube import YouTubeChannel, associate_videos

CHANNEL = 'UC' + 'B' * 22
VIDEO1 = 'abcdefghijk'
VIDEO2 = '123456789AB'


class YouTubeDiagnosticTests(unittest.TestCase):
    def run_diagnostic(self, projects, env, videos=None, settings=None, error=None):
        with TemporaryDirectory() as d:
            report_path = Path(d) / 'reports/youtube-diagnostics.json'
            with patch.object(YouTubeChannel, 'videos', side_effect=error if error else None,
                              return_value=videos if error is None else None):
                report = index_youtube(projects, settings or {'enabled': True, 'max_per_game': 5},
                                       env, report_path)
            self.assertTrue(report_path.is_file())
            self.assertEqual(report, json.loads(report_path.read_text()))
            return report

    def test_missing_channel_explicitly_reported(self):
        report = self.run_diagnostic([{'title': 'Hikari no Shima'}], {}, [])
        self.assertEqual(report['status'], 'missing_channel')
        self.assertFalse(report['channel_configured'])

    def test_key_presence_never_writes_value(self):
        projects = [{'repo': 'example/game', 'title': 'Venus Braves', 'youtube_url': ''}]
        report = self.run_diagnostic(projects, {'YOUTUBE_CHANNEL_ID': CHANNEL,
                   'YOUTUBE_API_KEY': 'MY_TOP_SECRET_VALUE'}, [
            {'id': VIDEO1, 'title': 'Venus & Braves PS2 English Patch'},
            {'id': VIDEO2, 'title': 'Completely unrelated tutorial'}])
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['videos_retrieved'], 2)
        self.assertEqual(report['videos_matched'], 1)
        self.assertEqual(report['videos'][0]['outcome'], 'matched')
        self.assertEqual(report['videos'][1]['outcome'], 'no_title_match')
        self.assertEqual(report['projects'][0]['channel_matches'][0]['id'], VIDEO1)
        self.assertNotIn('MY_TOP_SECRET_VALUE', json.dumps(report))

    def test_single_word_matching_limit_reported(self):
        report = self.run_diagnostic([{'repo': 'example/athena', 'title': 'Athena'}],
                                     {'YOUTUBE_CHANNEL_ID': CHANNEL},
                                     [{'id': VIDEO1, 'title': 'Athena gameplay PS1'}])
        self.assertTrue(report['projects'][0]['matching_limited'])
        self.assertEqual(report['videos'][0]['outcome'], 'no_title_match')

    def test_unknown_channel_format_redacted(self):
        report = self.run_diagnostic([], {'YOUTUBE_CHANNEL_ID': 'this-might-be-an-api-key'}, [])
        self.assertEqual(report['status'], 'error')
        self.assertEqual(report['channel'], '[invalid channel format]')
        self.assertNotIn('this-might-be-an-api-key', json.dumps(report))

    def test_sanitized_http_reason(self):
        body = BytesIO(json.dumps({'error': {'errors': [{'reason': 'quotaExceeded'}],
                                             'message': 'the-secret-value'}}).encode())
        client = YouTubeChannel(CHANNEL, 'the-secret-value')
        err = HTTPError('https://www.googleapis.com/youtube/v3/channels?key=the-secret-value',
                        403, 'Forbidden', {}, body)
        with patch('scripts.youtube.urlopen', side_effect=err):
            with self.assertRaisesRegex(RuntimeError, '403 \\(quotaExceeded\\)') as cm:
                client.videos()
        self.assertNotIn('the-secret-value', str(cm.exception))

    def test_summary_does_not_contain_video_titles(self):
        with TemporaryDirectory() as d:
            f = Path(d) / 'summary.txt'
            report = self.run_diagnostic([], {'YOUTUBE_CHANNEL_ID': CHANNEL,
                                               'GITHUB_STEP_SUMMARY': str(f)},
                                         [{'id': VIDEO1, 'title': 'Secret-looking but public video'}])
            text = f.read_text()
            self.assertIn('Videos retrieved: 1', text)
            self.assertNotIn('Secret-looking', text)
            self.assertEqual(report['videos'][0]['outcome'], 'no_title_match')

    def test_workflow_uploads_diagnostic_outside_site(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/pages.yml').read_text()
        self.assertIn('actions/upload-artifact@v4', workflow)
        self.assertIn('path: reports/youtube-diagnostics.json', workflow)
        self.assertIn('YOUTUBE_CHANNEL_ID: ${{ vars.YOUTUBE_CHANNEL_ID || secrets.YOUTUBE_CHANNEL_ID }}', workflow)
        self.assertIn('if: always()', workflow)


if __name__ == '__main__':
    unittest.main()
