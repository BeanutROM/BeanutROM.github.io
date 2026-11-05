"""Regression tests for fast, conditional catalog updates. No network."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import watch


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.repo = {
            "full_name": "demo-owner/PSX-JailBreaker-English-Patch",
            "pushed_at": "2026-10-30T12:00:00Z",
            "updated_at": "2026-10-30T12:00:00Z",
            "description": "English patch",
            "topics": ["translation"], "default_branch": "main",
        }
        self.project = {
            "repo": self.repo["full_name"], "title": "JailBreaker",
            "release_tag": "", "release_url": "", "youtube_urls": [],
            "igdb_title": "Jail Breaker", "youtube_match_titles": [],
        }
        self.youtube_state = {"status": "complete", "channel": "UC" + "A" * 22, "videos": []}
        self.state = watch.build_snapshot([self.repo], [self.project], self.youtube_state)

    def test_baseline_contains_only_public_metadata(self):
        self.assertEqual(self.state["schema_version"], 1)
        self.assertIn(self.repo["full_name"].lower(), self.state["repositories"])
        self.assertNotIn("GITHUB_TOKEN", json.dumps(self.state))
        self.assertEqual(self.state["youtube"]["projects"][0]["match_titles"][0], "JailBreaker")

    def test_no_changes(self):
        stamps = {self.repo["full_name"].lower(): watch.repo_stamp(self.repo)}
        self.assertEqual(watch.repo_changes(self.state, stamps), [])

    def test_repo_push_triggers(self):
        updated = dict(self.repo, pushed_at="2026-10-31T12:00:00Z")
        messages = watch.repo_changes(self.state, {self.repo["full_name"].lower(): watch.repo_stamp(updated)})
        self.assertTrue(any("pushed_at" in m for m in messages))

    def test_release_triggers_without_push(self):
        stamps = {self.repo["full_name"].lower(): watch.repo_stamp(
            self.repo, "v1.0", "https://github.com/demo-owner/PSX-JailBreaker-English-Patch/releases/tag/v1.0")}
        self.assertIn("release_tag", " ".join(watch.repo_changes(self.state, stamps)))

    def test_new_repo_and_deleted_repo(self):
        self.assertIn("New tracked repository", " ".join(watch.repo_changes(self.state, {
            **self.state["repositories"], "owner/new-game": watch.repo_stamp({})})))
        self.assertIn("Removed/untracked repository", " ".join(watch.repo_changes(self.state, {})))

    def test_unrelated_youtube_upload_does_not_deploy(self):
        videos = [{"id": "ABCDEFGHIJK", "title": "Unrelated upload"},
                  {"id": "LMNOPQRSTUV", "title": "Just another unrelated upload"}]
        self.assertEqual(watch.video_changes(self.state, videos), [])

    def test_new_matching_youtube_video_deploys(self):
        videos = [{"id": "LMNOPQRSTUV", "title": "JailBreaker PSX English Translation"}]
        self.assertIn("JailBreaker", " ".join(watch.video_changes(self.state, videos)))

    def test_renamed_youtube_video_now_matching_deploys(self):
        videos = [{"id": "ABCDEFGHIJK", "title": "JailBreaker PSX English Translation"}]
        self.assertIn("JailBreaker", " ".join(watch.video_changes(self.state, videos)))

    def test_existing_matched_video_does_not_repeat_deploy(self):
        matching = {"id": "ABCDEFGHIJK", "title": "JailBreaker PSX English Translation",
                    "game": self.repo["full_name"]}
        self.state["youtube"]["recent"] = [matching]
        self.assertEqual(watch.video_changes(self.state, [{"id": matching["id"], "title": matching["title"]}]), [])

    def test_site_url_personal_and_project(self):
        self.assertEqual(watch.site_url("demo-owner/demo-owner.github.io"), "https://demo-owner.github.io")
        self.assertEqual(watch.site_url("example/catalog"), "https://example.github.io/catalog")

    def test_manual_or_dispatch_does_not_need_network(self):
        for event in ("push", "workflow_dispatch", "repository_dispatch"):
            with patch.dict(os.environ, {"GITHUB_EVENT_NAME": event}, clear=True):
                with patch.object(watch, "fetch_snapshot", side_effect=AssertionError("Unexpected HTTP")):
                    with redirect_stdout(io.StringIO()):
                        watch.main()

    def test_scheduled_check_does_not_force_deploy(self):
        env = {"GITHUB_EVENT_NAME": "schedule",
               "GITHUB_REPOSITORY": "demo-owner/demo-owner.github.io"}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(watch, 'fetch_snapshot', return_value=self.state), \
             patch.object(watch, 'check_changes', return_value=[]) as checker, \
             patch.object(watch, 'write_step_output') as output, \
             patch.object(watch, 'GitHubAPI'):
            watch.main()
        checker.assert_called_once()
        self.assertEqual(output.call_args.args[0], False)

    def test_source_dispatch_still_forces_deploy(self):
        with patch.dict(os.environ,
                        {"GITHUB_EVENT_NAME": "repository_dispatch",
                         "CATALOG_DISPATCH_TYPE": "source_updated"}, clear=True), \
             patch.object(watch, 'fetch_snapshot', side_effect=AssertionError('unexpected poll')), \
             patch.object(watch, 'write_step_output') as output:
            watch.main()
        self.assertEqual(output.call_args.args[0], True)



if __name__ == "__main__":
    unittest.main()
