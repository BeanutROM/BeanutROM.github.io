"""Build-time thumbnail tests. Python standard library only; no Pillow."""
import io
import json
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from scripts import thumbnails

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://raw.githubusercontent.com/alice/game/main/assets/screenshots/01.png'


def png_sample(width=640, height=480):
    """Make a valid, noisy PNG using only the standard library."""
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    # Deterministic high-detail image, larger than the compressed preview.
    pixel_rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row += bytes(((x * 37 + y * 29) % 256, (x * 11 + y * 41) % 256, (x * y) % 256))
        pixel_rows.append(b'\x00' + row)
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(b''.join(pixel_rows), 6)) +
            chunk(b'IEND', b''))


class FakeResponse(io.BytesIO):
    headers = {}
    def geturl(self):
        return URL
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class ThumbnailTests(unittest.TestCase):
    def test_no_pillow_and_explicit_converter_install(self):
        src = (ROOT / 'scripts' / 'thumbnails.py').read_text()
        workflow = (ROOT / '.github/workflows/pages.yml').read_text()
        self.assertNotIn('from PIL', src)
        self.assertNotIn('import PIL', src)
        self.assertIn('apt-get install -y --no-install-recommends imagemagick', workflow)

    def test_output_is_local_and_original_remains_unchanged(self):
        payload = png_sample()
        with tempfile.TemporaryDirectory() as temp:
            projects = [{'repo':'alice/game', 'screenshots':[URL]}]
            with patch('scripts.thumbnails.urlopen', return_value=FakeResponse(payload)):
                stats = thumbnails.generate_thumbnails(projects, Path(temp))
            if thumbnails._converter():
                self.assertEqual(stats['generated'], 1)
                relative = projects[0]['screenshot_thumbnails'][0]
                self.assertTrue(relative.startswith('assets/thumbnails/'))
                image = Path(temp) / Path(relative).name
                self.assertTrue(image.is_file())
                self.assertLess(image.stat().st_size, len(payload))
                self.assertTrue(image.read_bytes().startswith(b'RIFF'))
            else:
                self.assertEqual(stats['fallback'], 1)
            self.assertEqual(projects[0]['screenshots'], [URL])

    def test_missing_converter_is_nonfatal(self):
        projects = [{'repo':'alice/game', 'screenshots':[URL]}]
        with tempfile.TemporaryDirectory() as temp, patch('scripts.thumbnails._converter', return_value=None):
            stats = thumbnails.generate_thumbnails(projects, Path(temp))
        self.assertEqual(stats['fallback'], 1)
        self.assertEqual(projects[0]['screenshot_thumbnails'], [''])

    def test_failed_download_falls_back_without_failing_build(self):
        projects = [{'repo':'alice/game', 'screenshots':[URL]}]
        with tempfile.TemporaryDirectory() as temp, patch('scripts.thumbnails._converter', return_value='convert'), \
             patch('scripts.thumbnails.urlopen', side_effect=OSError('no connection')):
            stats = thumbnails.generate_thumbnails(projects, Path(temp))
        self.assertEqual(stats['fallback'], 1)
        self.assertEqual(projects[0]['screenshot_thumbnails'], [''])

    def test_rejects_untrusted_hosts_without_network_call(self):
        with patch('scripts.thumbnails.urlopen') as opener:
            with self.assertRaises(ValueError):
                thumbnails._fetch_image('https://example.com/private.png', 2_000_000)
            opener.assert_not_called()

    def test_generated_thumbnail_is_reused_without_redownloading(self):
        payload = png_sample()
        with tempfile.TemporaryDirectory() as temp, patch('scripts.thumbnails.urlopen', return_value=FakeResponse(payload)) as opener:
            projects = [{'repo':'alice/game', 'screenshots':[URL, URL]}]
            result = thumbnails.generate_thumbnails(projects, Path(temp))
            if thumbnails._converter():
                self.assertEqual(result['cached'], 1)
                self.assertEqual(opener.call_count, 1)

    def test_gallery_uses_preview_and_viewer_uses_original(self):
        src = (ROOT / 'site/app.js').read_text(encoding='utf-8')
        self.assertIn('p.screenshot_thumbnails[index]', src)
        self.assertIn("poster:preview || src", src)
        self.assertIn('item.poster || item.src', src)
        self.assertIn('src="${escape(media.src)}"', src)


if __name__ == '__main__':
    unittest.main()
