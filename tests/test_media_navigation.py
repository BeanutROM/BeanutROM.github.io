"""Static regression checks for the browser media carousel, without test dependencies."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'site' / 'app.js').read_text(encoding='utf-8')
CSS = (ROOT / 'site' / 'styles.css').read_text(encoding='utf-8')
README = (ROOT / 'README.md').read_text(encoding='utf-8')


class MediaNavigationTests(unittest.TestCase):
    def test_arrows_use_ordered_media_gallery(self):
        self.assertIn('function viewerMarkup(p, media, gallery)', APP)
        self.assertIn('viewerMarkup(p, selected, media)', APP)
        self.assertIn('gallery.length > 1', APP)
        self.assertIn('data-media-step="-1"', APP)
        self.assertIn('data-media-step="1"', APP)
        self.assertIn('aria-label="Previous media"', APP)
        self.assertIn('aria-label="Next media"', APP)
        self.assertIn('viewer-counter', APP)

    def test_wraps_both_directions_and_updates_selected_item(self):
        self.assertIn('gallery[(index + direction + gallery.length) % gallery.length].id', APP)
        self.assertIn('state.selectedMedia = gallery[', APP)
        self.assertIn('galleryFor(project)', APP)
        self.assertIn('if (gallery.length < 2) return false;', APP)

    def test_keyboard_arrows_when_viewer_active(self):
        self.assertIn("e.key === 'ArrowLeft'", APP)
        self.assertIn("e.key === 'ArrowRight'", APP)
        self.assertIn('if (stepMedia(e.key ===', APP)
        self.assertIn('if (stepMedia(', APP)
        self.assertIn('if (e.key ===', APP)
        self.assertIn('if (!state.expanded || !state.selectedMedia) return false;', APP)
        self.assertIn('[contenteditable="true"]', APP)
        self.assertIn('if (stepMedia(e.key === \'ArrowLeft\' ? -1 : 1)) e.preventDefault();', APP)

    def test_navigation_controls_are_overlay_and_mobile_friendly(self):
        self.assertIn('.viewer-stage {position:relative;', CSS)
        self.assertIn('.viewer-nav {position:absolute;', CSS)
        self.assertIn('.viewer-prev {left:', CSS)
        self.assertIn('.viewer-next {right:', CSS)
        self.assertIn('.viewer-nav:focus-visible', CSS)
        self.assertIn('The viewer also has **Previous** and **Next** arrow buttons', README)


if __name__ == '__main__':
    unittest.main()
