"""Date-selection bitmask and accurate first-commit fallback."""
import unittest
from pathlib import Path
import json
from scripts import build


REPO = {
    'name': 'Example', 'full_name': 'demo/Example',
    'owner': {'login': 'demo'}, 'default_branch': 'main',
    'html_url': 'https://github.com/demo/Example', 'description': 'PS1 English patch',
    'topics': [], 'stargazers_count': 0,
    'pushed_at': '2026-11-01T23:00:00Z',
    'created_at': '2024-01-01T12:00:00Z',
}


def commit(when):
    return {'commit': {'committer': {'date': when}, 'author': {'date': when}}}


class API:
    def __init__(self):
        self.calls = []
        self.releases = []
        self.status_date = []
        self.assets_date = []
        self.latest_commit = [commit('2026-11-01T00:00:00Z')]
        self.earliest_commit = [commit('2024-02-15T00:00:00Z')]
        self.has_more_commits = True
        self.active_status = ''

    def get(self, path, params=None, optional=False):
        self.calls.append((path, params))
        if path.endswith('/releases'):
            return self.releases
        if '/git/trees/' in path:
            return {'tree': [{'type': 'blob', 'path': 'status.txt'}] if self.active_status else []}
        if path.endswith('/contents/status.txt'):
            if not self.active_status:
                return None
            import base64
            return {'encoding': 'base64', 'content': base64.b64encode(self.active_status.encode()).decode()}
        if path.endswith('/commits'):
            if params.get('path') == 'status.txt':
                return self.status_date
            if params.get('path') == 'assets':
                return self.assets_date
            return self.latest_commit
        if 'page=last' in path:
            return self.earliest_commit
        return None

    def pagination_link(self, path, params, rel='last'):
        if self.has_more_commits and params == {'per_page': 1}:
            return 'https://api.github.com/repos/demo/Example/commits?per_page=1&page=last'
        return ''


class UpdateFlagTests(unittest.TestCase):
    def test_default_flags_are_releases_and_status(self):
        self.assertEqual(build.DEFAULT_UPDATE_FLAGS, 3)
        self.assertEqual(build.parse_update_flags({}), 3)
        self.assertEqual(build.parse_update_flags({'updates': {'flags': 1 | 2}}), 3)
        self.assertEqual(json.loads((Path(build.ROOT) / 'config.json').read_text())['updates']['flags'], 3)

    def test_first_commit_used_if_no_selected_events(self):
        api = API()
        result = build.make_project(api, REPO, {})
        self.assertEqual(result['updated_at'], '2024-02-15T00:00:00Z')
        # The repository's created_at, latest pushed_at, and newest commit are not used.
        self.assertNotEqual(result['updated_at'], REPO['created_at'])
        self.assertNotEqual(result['updated_at'], REPO['pushed_at'])
        self.assertNotEqual(result['updated_at'], api.latest_commit[0]['commit']['committer']['date'])
        self.assertTrue(any('page=last' in p for p, _ in api.calls))
        self.assertFalse(any(q and q.get('path') == 'assets' for _, q in api.calls))

    def test_release_or_status_newest_wins_by_default(self):
        api = API()
        api.releases = [{'draft': False, 'tag_name': 'v1', 'published_at': '2026-08-01T00:00:00Z'}]
        api.status_date = [commit('2026-09-01T00:00:00Z')]
        self.assertEqual(build.make_project(api, REPO, {})['updated_at'], '2026-09-01T00:00:00Z')
        self.assertFalse(any(q == {'per_page': 1} for _, q in api.calls))

    def test_asset_flag_only_counts_asset_commits_not_every_push(self):
        api = API()
        api.assets_date = [commit('2026-10-01T00:00:00Z')]
        self.assertEqual(build.make_project(api, REPO, {}, update_flags=4)['updated_at'], '2026-10-01T00:00:00Z')
        self.assertTrue(any(q == {'path': 'assets', 'per_page': 1} for _, q in api.calls))

    def test_any_commit_bit_includes_all_commits(self):
        api = API()
        api.assets_date = [commit('2026-09-01T00:00:00Z')]
        self.assertEqual(build.make_project(api, REPO, {}, update_flags=8)['updated_at'], '2026-11-01T00:00:00Z')
        self.assertFalse(any(q and q.get('path') for _, q in api.calls))
        self.assertEqual(build.make_project(api, REPO, {}, update_flags=15)['updated_at'], '2026-11-01T00:00:00Z')

    def test_flags_zero_always_earliest_commit(self):
        api = API()
        api.status_date = [commit('2026-10-01T00:00:00Z')]
        api.releases = [{'draft': False, 'tag_name': 'v1', 'published_at': '2026-10-02T00:00:00Z'}]
        result = build.make_project(api, REPO, {}, update_flags=0)
        self.assertEqual(result['updated_at'], '2024-02-15T00:00:00Z')
        self.assertFalse(any(q and q.get('path') for _, q in api.calls))
        self.assertEqual(result['status'], 'Released')

    def test_no_pagination_means_single_commit(self):
        api = API()
        api.has_more_commits = False
        api.latest_commit = [commit('2025-01-01T00:00:00Z')]
        self.assertEqual(build.first_commit_date(api, REPO), '2025-01-01T00:00:00Z')
        self.assertEqual(len(api.calls), 1)

    def test_empty_repo_has_no_commit_date(self):
        api = API()
        api.latest_commit = []
        self.assertEqual(build.first_commit_date(api, REPO), '')

    def test_empty_repository_uses_creation_date(self):
        api = API()
        api.latest_commit = []
        self.assertEqual(build.make_project(api, REPO, {})['updated_at'], REPO['created_at'])
        self.assertEqual(build.make_project(api, REPO, {}, update_flags=0)['updated_at'], REPO['created_at'])

    def test_repo_created_at_only_used_after_commit_fallback(self):
        api = API()
        self.assertEqual(build.make_project(api, REPO, {}, update_flags=0)['updated_at'],
                         '2024-02-15T00:00:00Z')
        api.latest_commit = []
        api.releases = [{'draft': False, 'tag_name': 'v1',
                         'published_at': '2026-08-01T00:00:00Z'}]
        self.assertEqual(build.make_project(api, REPO, {})['updated_at'],
                         '2026-08-01T00:00:00Z')

    def test_invalid_or_missing_creation_date_falls_back_to_empty(self):
        api = API()
        api.latest_commit = []
        for created_at in ('', 'not-a-date', None):
            with self.subTest(created_at=created_at):
                repo = dict(REPO, created_at=created_at)
                self.assertEqual(build.make_project(api, repo, {})['updated_at'], '')

    def test_empty_repository_api_conflict_uses_creation_date(self):
        class EmptyRepositoryAPI(API):
            def get(self, path, params=None, optional=False):
                if path.endswith('/commits'):
                    raise RuntimeError('HTTP 409: Git Repository is empty')
                return super().get(path, params, optional)

        self.assertEqual(build.make_project(EmptyRepositoryAPI(), REPO, {})['updated_at'],
                         REPO['created_at'])

    def test_flags_validation(self):
        for invalid in (-1, 16, 3.0, '3', True, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                build.parse_update_flags({'updates': {'flags': invalid}})
        self.assertEqual(build.parse_update_flags({'updates': {'flags': 15}}), 15)

    def test_pagination_link_header_parsing(self):
        gh = build.GitHubAPI()
        path = '/repos/demo/Example/commits'
        params = {'per_page': 1}
        url = 'https://api.github.com/repos/demo/Example/commits?per_page=1'
        gh.link_headers[url] = ('<https://api.github.com/repos/demo/Example/commits?per_page=1&page=2>; rel="next", '
                                '<https://api.github.com/repos/demo/Example/commits?per_page=1&page=40>; rel="last"')
        self.assertEqual(gh.pagination_link(path, params, 'last'),
                         'https://api.github.com/repos/demo/Example/commits?per_page=1&page=40')
        gh.link_headers[url] = '<https://not-github.test/anything>; rel="last"'
        self.assertEqual(gh.pagination_link(path, params), '')


if __name__ == '__main__':
    unittest.main()
