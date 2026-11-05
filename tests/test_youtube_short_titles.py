"""Short-title matching must use exact game title, console and patch context."""
import unittest

from scripts.watch import build_snapshot, video_changes
from scripts.youtube import associate_videos, contextual_short_score


ENIGMA_TITLE = "Enigma PSX English Translation - Work in progress preview"
ENIGMA_VIDEO = {"id": "Qwerty12347", "title": ENIGMA_TITLE}


class ShortTitleYouTubeTests(unittest.TestCase):
    def make_enigma(self):
        return {
            "repo": "demo-owner/PSX-Enigma-English-Patch",
            "title": "Enigma", "platform": "PS1", "platforms": ["PS1"],
            "youtube_urls": [],
        }

    def test_enigma_video_auto_matches(self):
        project = self.make_enigma()
        associate_videos([project], [ENIGMA_VIDEO])
        self.assertEqual(len(project["youtube_videos"]), 1)

    def test_platform_alias_and_mixed_platform_fallback(self):
        project = self.make_enigma()
        for title in ("Enigma PlayStation 1 English Patch", "PSX Enigma English Translation",
                      "Enigma PS1 English Translation"):
            with self.subTest(title=title):
                self.assertGreater(contextual_short_score("Enigma", title, project), 0)
        self.assertGreater(contextual_short_score(
            "Enigma", "Enigma PSX English Translation",
            {"title": "Enigma", "platforms": ["PS1", "PS2"]}), 0)

    def test_reject_wrong_console_missing_context_and_unrelated_mentions(self):
        project = self.make_enigma()
        rejected = (
            "Enigma PS2 English Translation",  # PS2 is not PS1
            "Enigma English Translation Preview",  # no console
            "Enigma PSX Gameplay",  # no explicit translation/patch mention
            "Enigma PSX English Gameplay",  # English alone is insufficient
            "Enigma II PSX English Translation",  # sequel
            "Enigma 2 PSX English Translation",  # sequel
            "Enigmatic PSX English Translation",  # substring is not a title
            "The Enigma of PSX English Translation",  # generic word in a phrase
            "My Favorite Enigma PSX English Translation",  # unrelated prefix
        )
        for title in rejected:
            with self.subTest(title=title):
                self.assertEqual(contextual_short_score("Enigma", title, project), 0)

    def test_ambiguous_same_title_same_platform_rejected(self):
        projects = [self.make_enigma(), dict(self.make_enigma(), repo="other/PSX-Enigma")]
        associate_videos(projects, [ENIGMA_VIDEO])
        self.assertEqual(projects[0]["youtube_videos"], [])
        self.assertEqual(projects[1]["youtube_videos"], [])

    def test_same_title_different_console_picks_compatible_game(self):
        ps1 = self.make_enigma()
        ps2 = {"repo": "other/PS2-Enigma", "title": "Enigma", "platforms": ["PS2"]}
        associate_videos([ps1, ps2], [ENIGMA_VIDEO])
        self.assertEqual(len(ps1["youtube_videos"]), 1)
        self.assertEqual(ps2["youtube_videos"], [])

    def test_short_generic_word_requires_all_context(self):
        egg = {"repo": "demo-owner/PSX-Egg-English-Patch", "title": "Egg", "platforms": ["PS1"]}
        self.assertGreater(contextual_short_score("Egg", "Egg PSX English Translation", egg), 0)
        for video in ("Egg PSX Gameplay", "Easter Egg PSX English Translation", "Egg PS2 English Translation"):
            self.assertEqual(contextual_short_score("Egg", video, egg), 0)
        self.assertEqual(contextual_short_score("Go", "Go PSX English Translation", egg), 0)

    def test_watch_detects_new_short_title_video_without_repeated_deploy(self):
        repo = {"full_name": "demo-owner/PSX-Enigma-English-Patch"}
        project = self.make_enigma()
        state = build_snapshot([repo], [project], {
            "status": "complete", "channel": "UC" + "X" * 22, "videos": [],
        })
        self.assertEqual(state["youtube"]["projects"][0]["platforms"], ["PS1"])
        self.assertTrue(video_changes(state, [ENIGMA_VIDEO]))
        state["youtube"]["recent"] = [{"id": ENIGMA_VIDEO["id"], "title": ENIGMA_TITLE,
                                         "game": project["repo"]}]
        self.assertEqual(video_changes(state, [ENIGMA_VIDEO]), [])


if __name__ == "__main__":
    unittest.main()
