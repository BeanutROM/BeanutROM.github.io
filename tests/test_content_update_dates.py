"""The visible update date reflects releases or root status.txt, not repo pushes."""
import unittest
from pathlib import Path
from scripts import build


class API:
    def __init__(self, releases=None, commits=None, status='', first_commits=None):
        self.releases = releases or []
        self.commits = commits or []
        self.first_commits = first_commits or []
        self.status = status
        self.calls = []

    def get(self, path, params=None, optional=False):
        self.calls.append((path, params))
        if path.endswith('/releases'):
            return self.releases
        if path.endswith('/commits'):
            return self.commits if params.get('path') == 'status.txt' else self.first_commits
        if '/git/trees/' in path:
            return {'tree': [{'path': 'status.txt', 'type': 'blob'}] if self.status else []}
        if '/contents/status.txt' in path:
            import base64
            return {'encoding': 'base64', 'content': base64.b64encode(self.status.encode()).decode()} if self.status else None
        return None


def repo(push='2026-11-01T23:59:00Z'):
    return {
        'name': 'Example-Game', 'full_name': 'example/Example-Game',
        'owner': {'login': 'example'}, 'default_branch': 'main',
        'description': 'An English patch for an older PS1 game',
        'pushed_at': push, 'updated_at': push,
        'html_url': 'https://github.com/example/Example-Game',
        'topics': [], 'stargazers_count': 0,
    }


def commit(date):
    return {'commit': {'committer': {'date': date}, 'author': {'date': date}}}


class ContentUpdateDateTests(unittest.TestCase):
    def test_assets_only_pushes_do_not_change_date(self):
        api = API()
        older = build.make_project(api, repo('2026-09-01T00:00:00Z'), {})
        newer = build.make_project(api, repo('2026-11-01T00:00:00Z'), {})
        self.assertEqual(older['updated_at'], '')
        self.assertEqual(newer['updated_at'], '')
        self.assertTrue(any(p.endswith('/commits') and q == {'path': 'status.txt', 'per_page': 1} for p, q in api.calls))

    def test_status_file_commit_date_only(self):
        api = API(commits=[commit('2026-10-23T12:15:00Z')], status='Paused')
        project = build.make_project(api, repo(), {})
        self.assertEqual(project['updated_at'], '2026-10-23T12:15:00Z')
        self.assertEqual(project['status'], 'Paused')

    def test_removing_status_file_is_tracked(self):
        api = API(commits=[commit('2026-10-25T00:00:00Z')])
        project = build.make_project(api, repo(), {})
        self.assertEqual(project['status'], 'In-Progress')
        self.assertEqual(project['updated_at'], '2026-10-25T00:00:00Z')

    def test_latest_release_activity_wins_over_older_status_change(self):
        api = API(releases=[{
            'draft': False, 'tag_name': 'v2-Beta',
            'published_at': '2026-10-20T00:00:00Z',
            'updated_at': '2026-10-28T08:00:00Z',
        }], commits=[commit('2026-10-15T03:00:00Z')], status='Paused')
        project = build.make_project(api, repo(), {})
        self.assertEqual(project['updated_at'], '2026-10-28T08:00:00Z')
        self.assertEqual(project['status'], 'Released')
        self.assertEqual(project['release_stage'], 'Beta')

    def test_status_change_can_be_newer_than_published_release(self):
        api = API(releases=[{'draft': False, 'tag_name': 'v1', 'published_at': '2026-09-01T00:00:00Z'}],
                  commits=[commit('2026-10-29T03:00:00Z')], status='Paused')
        project = build.make_project(api, repo(), {})
        self.assertEqual(project['updated_at'], '2026-10-29T03:00:00Z')
        self.assertEqual(project['status'], 'Released')

    def test_edit_to_older_published_release_counts(self):
        api = API(releases=[
            {'draft': False, 'tag_name': 'v2', 'published_at': '2026-10-10T00:00:00Z'},
            {'draft': False, 'tag_name': 'v1', 'published_at': '2026-09-01T00:00:00Z',
             'updated_at': '2026-10-26T00:00:00Z'},
        ])
        project = build.make_project(api, repo(), {})
        self.assertEqual(project['release_tag'], 'v2')
        self.assertEqual(project['updated_at'], '2026-10-26T00:00:00Z')

    def test_draft_dates_ignored(self):
        api = API(releases=[{'draft': True, 'tag_name': 'v3', 'updated_at': '2026-11-01T00:00:00Z'}])
        self.assertEqual(build.make_project(api, repo(), {})['updated_at'], '')

    def test_unavailable_optional_status_history_does_not_fail_build(self):
        class FailedHistory(API):
            def get(self, path, params=None, optional=False):
                if path.endswith('/commits'):
                    raise RuntimeError('HTTP 409: empty repository')
                return super().get(path, params, optional)
        self.assertEqual(build.make_project(FailedHistory(), repo(), {})['updated_at'], '')

    def test_bad_dates_do_not_fallback_to_push(self):
        api = API(releases=[{'draft': False, 'tag_name': 'v1', 'published_at': '???'}],
                  commits=[commit('not-a-date')])
        self.assertEqual(build.make_project(api, repo(), {})['updated_at'], '')


if __name__ == '__main__':
    unittest.main()
