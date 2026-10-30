"""Generate small, local WebP gallery previews from public repository screenshots.

Uses the ImageMagick command-line application, not Python Imaging Library/Pillow.
Only thumbnails are included in the Pages artifact. Original images remain on GitHub.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_SOURCE_BYTES = 16 * 1024 * 1024
THUMB_DIR = Path('site/assets/thumbnails')


def _image_type(payload):
    if payload.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if payload.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if len(payload) >= 12 and payload.startswith(b'RIFF') and payload[8:12] == b'WEBP':
        return 'webp'
    return ''


def _fetch_image(url, max_bytes):
    """Download a limited-size public GitHub image (never fetch arbitrary hosts)."""
    parts = urlparse(str(url))
    if parts.scheme != 'https' or parts.hostname != 'raw.githubusercontent.com' or parts.username or parts.password or parts.port:
        raise ValueError('Only HTTPS raw.githubusercontent.com screenshot URLs are downloaded')
    if not parts.path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        raise ValueError('Unsupported screenshot image extension')
    request = Request(url, headers={'User-Agent': 'game-catalog-thumbnail-builder/1.0'})
    with urlopen(request, timeout=20) as response:
        final = urlparse(response.geturl())
        if final.scheme != 'https' or final.hostname != 'raw.githubusercontent.com':
            raise ValueError('Unexpected screenshot redirect')
        header_length = response.headers.get('Content-Length')
        if header_length and int(header_length) > max_bytes:
            raise ValueError('Screenshot exceeds size limit')
        payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError('Screenshot exceeds size limit')
    kind = _image_type(payload)
    if not kind:
        raise ValueError('Screenshot is not a supported image')
    return payload, kind


def _converter():
    return shutil.which('magick') or shutil.which('convert')


def _make_thumbnail(payload, kind, output, converter, width, quality):
    # ImageMagick's memory/map/disk limits help bound untrusted image decoding.
    with tempfile.TemporaryDirectory(prefix='catalog-thumb-') as temp:
        source = Path(temp) / ('source.' + kind)
        result = Path(temp) / 'thumb.webp'
        source.write_bytes(payload)
        cmd = [converter, '-limit', 'memory', '128MiB', '-limit', 'map', '256MiB',
               '-limit', 'disk', '512MiB', str(source), '-auto-orient',
               '-thumbnail', f'{width}x{width}>', '-strip', '-quality', str(quality),
               str(result)]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if done.returncode != 0 or not result.is_file() or result.stat().st_size == 0:
            raise RuntimeError((done.stderr or 'ImageMagick conversion failed').strip()[:200])
        # Never replace a tiny original with a larger thumbnail.
        if result.stat().st_size >= len(payload):
            return False
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(result, output)
        return True


def generate_thumbnails(projects, output_dir, settings=None):
    """Add screenshot_thumbnails arrays, aligned with each project's screenshots.

    On errors, leave a blank entry for that image. The browser will fall back to
    the original URL, so image conversion cannot prevent catalog deployment.
    """
    settings = settings or {}
    enabled = bool(settings.get('enabled', True))
    width = max(96, min(640, int(settings.get('width', 320))))
    quality = max(35, min(95, int(settings.get('quality', 76))))
    max_bytes = max(1024, min(32 * 1024 * 1024, int(settings.get('max_source_bytes', MAX_SOURCE_BYTES))))
    destination = Path(output_dir)
    converter = _converter() if enabled else None
    stats = {'generated': 0, 'cached': 0, 'fallback': 0, 'total': 0}
    if enabled and not converter:
        print('WARN: ImageMagick not found; full-size screenshots will remain in gallery thumbnails.', file=sys.stderr)
    for project in projects:
        shots = project.get('screenshots')
        if not isinstance(shots, list):
            shots = []
        previews = []
        for url in shots:
            stats['total'] += 1
            if not enabled or not converter:
                previews.append('')
                stats['fallback'] += 1
                continue
            # Stable cache key: original URL, not game order or release status.
            # Rebuilt during the scheduled catalog update; no old screenshots
            # or stale thumbnail URLs survive in the published site.
            key = hashlib.sha256((str(url) + f'|{width}|{quality}|v1').encode('utf-8')).hexdigest()[:24]
            relative = f'assets/thumbnails/{key}.webp'
            target = destination / f'{key}.webp'
            if target.is_file() and target.stat().st_size > 0:
                previews.append(relative)
                stats['cached'] += 1
                continue
            try:
                data, kind = _fetch_image(url, max_bytes)
                if _make_thumbnail(data, kind, target, converter, width, quality):
                    previews.append(relative)
                    stats['generated'] += 1
                else:
                    previews.append('')
                    stats['fallback'] += 1
            except (ValueError, HTTPError, URLError, TimeoutError, OSError,
                    RuntimeError, subprocess.TimeoutExpired) as exc:
                print(f'WARN: Thumbnail unavailable for {project.get("repo", "game")}: {str(exc)[:170]}', file=sys.stderr)
                previews.append('')
                stats['fallback'] += 1
        project['screenshot_thumbnails'] = previews
    print('Screenshot thumbnails: {generated} generated, {cached} reused, '
          '{fallback} original-image fallbacks / {total} screenshots.'.format(**stats))
    return stats
