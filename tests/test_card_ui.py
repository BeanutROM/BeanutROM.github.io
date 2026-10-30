"""Make sure title cards show dates, not repository owner attribution."""
from pathlib import Path
import unittest

class CardUITests(unittest.TestCase):
    def test_fallback_cover_has_no_game_sequence_number(self):
        app = (Path(__file__).resolve().parents[1] / 'site/app.js').read_text()
        css = (Path(__file__).resolve().parents[1] / 'site/styles.css').read_text()
        self.assertNotIn('GAME /', app)
        self.assertNotIn('poster-index', app)
        self.assertNotIn('.poster-index', css)
        self.assertNotIn('${placeholder(p)}', app)
        self.assertIn('` : placeholder(p)}', app)
        self.assertIn('${cover ? `<img', app)
        self.assertIn("platformBadges(p, 'image-platform')", app)

    def test_owner_removed_from_card_but_date_remains(self):
        app = (Path(__file__).resolve().parents[1] / 'site/app.js').read_text()
        section = app.split('function projectCard(p)', 1)[1].split('function viewerMarkup(', 1)[0]
        self.assertIn('Updated ${escape(shortDate(p.updated_at))}', section)
        self.assertNotIn('p.owner', section)
        self.assertIn('data-open=', section)

if __name__ == '__main__':
    unittest.main()
