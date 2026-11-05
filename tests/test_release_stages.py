"""Release-stage badges are based on the latest published tag, not on prerelease flags."""
from pathlib import Path
import unittest

from scripts import build
from test_build import FakeApi, example

ROOT = Path(__file__).resolve().parents[1]


class ReleaseStageTests(unittest.TestCase):
    def test_tag_stage_detection_and_false_positives(self):
        tags = {
            'v0.4-Alpha': 'Alpha',
            'v0.7_BETA': 'Beta',
            'v0.4Alpha': 'Alpha',
            'v0.7Beta2': 'Beta',
            'Alpha-v0.1': 'Alpha',
            'v1.2-beta.2': 'Beta',
            'v1.0': '',
            'v2.3-rc1': '',
            'alphabet-v1.0': '',
            'betamax-v1.0': '',
            '': '',
        }
        for tag, expected in tags.items():
            with self.subTest(tag=tag):
                self.assertEqual(build.release_stage_from_tag(tag), expected)

    def test_latest_published_tag_controls_stage_and_status(self):
        releases = [
            {'draft': False, 'tag_name': 'v0.4-Alpha', 'published_at': '2026-01-01T00:00:00Z'},
            {'draft': False, 'tag_name': 'v0.7-Beta', 'published_at': '2026-05-01T00:00:00Z',
             'html_url': 'https://github.com/alice/translation/releases/tag/v0.7-Beta'},
        ]
        project = build.make_project(FakeApi(releases=releases), example(), {})
        self.assertEqual(project['status'], 'Released')
        self.assertEqual(project['release_tag'], 'v0.7-Beta')
        self.assertEqual(project['release_stage'], 'Beta')
        self.assertIn('v0.7-Beta', project['release_url'])

    def test_new_stable_release_clears_old_beta_badge(self):
        releases = [
            {'draft': False, 'prerelease': True, 'tag_name': 'v0.7-beta',
             'published_at': '2026-01-01T00:00:00Z'},
            {'draft': False, 'prerelease': False, 'tag_name': 'v1.0',
             'published_at': '2026-06-01T00:00:00Z'},
        ]
        project = build.make_project(FakeApi(releases=releases), example(), {})
        self.assertEqual((project['status'], project['release_tag'], project['release_stage']),
                         ('Released', 'v1.0', ''))

    def test_prerelease_flag_does_not_invent_stage(self):
        release = {'draft': False, 'prerelease': True, 'tag_name': 'v0.8',
                   'published_at': '2026-10-01T00:00:00Z'}
        project = build.make_project(FakeApi(releases=[release]), example(), {})
        self.assertEqual(project['status'], 'Released')
        self.assertEqual(project['release_stage'], '')

    def test_draft_and_unreleased_games_cannot_show_stage(self):
        api = FakeApi(releases=[{'draft': True, 'tag_name': 'v2.0-Alpha'}])
        project = build.make_project(api, example(), {})
        self.assertEqual(project['status'], 'In-Progress')
        self.assertEqual(project['release_stage'], '')
        self.assertFalse(project['has_release'])

    def test_override_cannot_falsify_release_stage(self):
        project = build.make_project(FakeApi(), example(),
                                     {'alice/translation': {'release_stage': 'Beta', 'status': 'Released'}})
        self.assertEqual(project['status'], 'In-Progress')
        self.assertEqual(project['release_stage'], '')


if __name__ == '__main__':
    unittest.main()
