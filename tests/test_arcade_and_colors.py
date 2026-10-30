"""MAME detection, color palette export and official title spelling."""
import json
import unittest
from pathlib import Path
from scripts.build import PLATFORM_VARIANTS, platforms_in_text, detect_platforms, display_title, configured_platforms
from scripts.igdb import platform_matches

ROOT = Path(__file__).resolve().parents[1]

class ArcadePaletteTests(unittest.TestCase):
    def test_arcade_aliases_group_as_mame(self):
        examples = [
            "ST-V", "STV", "Sega Titan Video", "Sega Titan Video System",
            "MAME", "Arcade", "CPS-1", "CPS2", "CPS-3", "NAOMI", "NAOMI 2",
            "Atomiswave", "Sega Model 2", "Sega System 16", "Neo Geo MVS",
            "Taito Type X", "Triforce", "Sega Chihiro", "Namco System 22"
        ]
        for name in examples:
            with self.subTest(name=name):
                self.assertEqual(platforms_in_text(name), ["MAME"])
                repo = {"name":f"{name}-Example-Game-English-Patch", "description":"", "topics":[]}
                self.assertEqual(detect_platforms(repo), ["MAME"])

    def test_canonical_consoles_not_merged_with_arcade(self):
        self.assertEqual(platforms_in_text("Sega Saturn"), ["Saturn"])
        self.assertEqual(platforms_in_text("Neo Geo AES"), ["Neo Geo"])
        self.assertEqual(platforms_in_text("Dreamcast"), ["Dreamcast"])
        self.assertEqual(platforms_in_text("GameCube"), ["GameCube"])

    def test_arcade_override_is_canonicalized(self):
        self.assertEqual(configured_platforms({'platform':'ST-V'}, ['Saturn']), ['MAME'])
        self.assertEqual(configured_platforms({'platforms':['ST-V','PSX']}, []), ['MAME','PS1'])

    def test_mame_igdb_maps_to_arcade(self):
        self.assertTrue(platform_matches("MAME", [{"name":"Arcade","abbreviation":"ARC"}]))
        self.assertFalse(platform_matches("MAME", [{"name":"Sega Saturn"}]))
        self.assertTrue(platform_matches(["MAME", "PS1"], [{"name":"Arcade"}]))

    def test_jailbreaker_official_spelling(self):
        for repo_name in ("PSX-JailBreaker-English-Patch", "PSX-Jail-Breaker-English-Patch"):
            with self.subTest(repo=repo_name):
                self.assertEqual(display_title({"name":repo_name}, "PS1"), "JailBreaker")
        self.assertEqual(display_title({"name":"PSX-JailBreaker-II-English-Patch"}, "PS1"), "Jail Breaker II")

    def test_every_platform_has_configured_colors(self):
        config = json.loads((ROOT/'platform-colors.json').read_text())
        colors = config
        self.assertEqual(set(PLATFORM_VARIANTS) | {'Other'}, set(colors))
        for name, pair in colors.items():
            with self.subTest(platform=name):
                self.assertRegex(pair['background'], r'^#[0-9a-fA-F]{6}$')
                self.assertRegex(pair['text'], r'^#[0-9a-fA-F]{6}$')

    def test_build_exports_palette_and_browser_applies_it(self):
        code = (ROOT/'scripts/build.py').read_text()
        app = (ROOT/'site/app.js').read_text()
        css = (ROOT/'site/styles.css').read_text()
        self.assertIn('"platform_colors": load_platform_colors()', code)
        self.assertIn('state.platformColors =', app)
        self.assertIn("platformBadges(p, 'image-platform')", app)
        self.assertIn("platformBadges(p, 'detail-platform')", app)
        self.assertIn('--platform-bg', css)
        self.assertIn('--platform-fg', css)
        demo = json.loads((ROOT/'site/data/projects.json').read_text())
        self.assertIn('MAME', demo['platform_colors'])

if __name__ == '__main__':
    unittest.main()
