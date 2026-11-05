"""Generate small, local WebP gallery previews from public repository screenshots.

Uses the ImageMagick command-line application, not Python Imaging Library/Pillow.
Only thumbnails are included in the Pages artifact. Original images remain on GitHub.
"""
from __future__ import annotations

import hashlib
import json
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


def _identify_dimensions(converter, source):
    """Read original pixel dimensions using ImageMagick, without Pillow."""
    args = [converter]
    if Path(converter).name == 'magick':
        args.append('identify')
    args += ['-limit', 'memory', '128MiB', '-limit', 'map', '256MiB',
             '-ping', '-format', '%w %h', str(source)]
    if Path(converter).name != 'magick':
        args.append('info:')
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
        if result.returncode == 0:
            width, height = (int(v) for v in result.stdout.strip().split())
            if 0 < width <= 32768 and 0 < height <= 32768:
                return [width, height]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def _make_thumbnail(payload, kind, output, converter, width, quality):
    # ImageMagick's memory/map/disk limits help bound untrusted image decoding.
    with tempfile.TemporaryDirectory(prefix='catalog-thumb-') as temp:
        source = Path(temp) / ('source.' + kind)
        result = Path(temp) / 'thumb.webp'
        source.write_bytes(payload)
        dimensions = _identify_dimensions(converter, source)
        cmd = [converter, '-limit', 'memory', '128MiB', '-limit', 'map', '256MiB',
               '-limit', 'disk', '512MiB', str(source), '-auto-orient',
               '-thumbnail', f'{width}x{width}>', '-strip', '-quality', str(quality),
               str(result)]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if done.returncode != 0 or not result.is_file() or result.stat().st_size == 0:
            raise RuntimeError((done.stderr or 'ImageMagick conversion failed').strip()[:200])
        # Never replace a tiny original with a larger thumbnail.
        if result.stat().st_size >= len(payload):
            return False, dimensions
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(result, output)
        return True, dimensions


def _load_manifest(cache_root):
    if cache_root is None:
        return {}
    path = cache_root / 'thumbnail-manifest.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict) and data.get('schema_version') == 2 and isinstance(data.get('entries'), dict):
            return data['entries']
    except (OSError, ValueError):
        pass
    return {}


def _valid_revision(value):
    return isinstance(value, str) and len(value) in (40, 64) and all(c in '0123456789abcdefABCDEF' for c in value)


def _valid_cached_thumbnail(path, expected):
    try:
        return (path.is_file() and not path.is_symlink() and path.stat().st_size > 0
                and hashlib.sha256(path.read_bytes()).hexdigest() == expected
                and path.read_bytes()[:4] == b'RIFF')
    except (OSError, ValueError):
        return False


def generate_thumbnails(projects, output_dir, settings=None, cache_dir=None):
    """Create only previews referenced by today's GitHub file trees.

    Durable hits require a Git blob SHA for the current screenshot and a
    verified thumbnail hash. The URL alone is *never* sufficient for persistent
    reuse. Removed images cannot be resurrected from a previous manifest.
    """
    settings = settings or {}
    enabled = bool(settings.get('enabled', True))
    width = max(96, min(640, int(settings.get('width', 320))))
    quality = max(35, min(95, int(settings.get('quality', 76))))
    max_bytes = max(1024, min(32 * 1024 * 1024, int(settings.get('max_source_bytes', MAX_SOURCE_BYTES))))
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    cache_root = Path(cache_dir) if cache_dir else None
    manifest = _load_manifest(cache_root)
    next_manifest = {}
    local_dimensions = {}
    converter = _converter() if enabled else None
    stats = {'generated': 0, 'cached': 0, 'fallback': 0, 'total': 0, 'removed': 0}
    if enabled and not converter:
        print('WARN: ImageMagick not found; full-size screenshots will remain in gallery thumbnails.', file=sys.stderr)

    for project in projects:
        shots = project.get('screenshots')
        if not isinstance(shots, list):
            shots = []
        revisions = project.get('_screenshot_revisions') or {}
        valid_urls, previews, dimensions = [], [], []
        for url in shots:
            stats['total'] += 1
            revision = revisions.get(url)
            verified = _valid_revision(revision)
            # A new digest algorithm/quality/source SHA invalidates the preview.
            identity = f'{url}|{revision if verified else "unverified"}|{width}|{quality}|v2'
            key = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
            relative = f'assets/thumbnails/{key}.webp'
            target = destination / (key + '.webp')
            entry = manifest.get(key) if verified else None
            used = False
            if enabled and isinstance(entry, dict) and (entry.get('url') == url and entry.get('source_sha') == revision
                      and entry.get('width') == width and entry.get('quality') == quality):
                source = cache_root / 'thumbnails' / (key + '.webp')
                thumb_sha = entry.get('thumbnail_sha256')
                if isinstance(thumb_sha, str) and _valid_cached_thumbnail(source, thumb_sha):
                    shutil.copyfile(source, target)
                    dims = entry.get('dimensions')
                    dimensions.append(dims if isinstance(dims, list) and len(dims) == 2 else None)
                    previews.append(relative)
                    valid_urls.append(url)
                    next_manifest[key] = entry
                    local_dimensions[key] = dimensions[-1]
                    stats['cached'] += 1
                    used = True
            if used:
                continue
            # Keep reusing an immutable preview within this single invocation
            # if a screenshot is referenced by multiple projects.
            if enabled and converter and target.is_file() and target.stat().st_size > 0:
                previews.append(relative)
                dimensions.append(local_dimensions.get(key))
                valid_urls.append(url)
                stats['cached'] += 1
                continue
            if not enabled or not converter:
                valid_urls.append(url)
                previews.append('')
                dimensions.append(None)
                stats['fallback'] += 1
                continue
            try:
                data, kind = _fetch_image(url, max_bytes)
                created, image_dimensions = _make_thumbnail(data, kind, target, converter, width, quality)
                valid_urls.append(url)
                dimensions.append(image_dimensions)
                local_dimensions[key] = image_dimensions
                if created:
                    previews.append(relative)
                    stats['generated'] += 1
                    if cache_root is not None and verified:
                        source = cache_root / 'thumbnails' / (key + '.webp')
                        source.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(target, source)
                        next_manifest[key] = {
                            'url': url, 'source_sha': revision, 'width': width,
                            'quality': quality, 'dimensions': image_dimensions,
                            'thumbnail_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        }
                else:
                    previews.append('')
                    stats['fallback'] += 1
            except HTTPError as exc:
                if exc.code in (404, 410):
                    stats['removed'] += 1
                    if project.get('cover_url') == url:
                        project['cover_url'] = ''
                    print(f'WARN: Removed missing screenshot from {project.get("repo", "game")}: {url}', file=sys.stderr)
                    continue
                valid_urls.append(url)
                previews.append('')
                dimensions.append(None)
                stats['fallback'] += 1
            except (ValueError, URLError, TimeoutError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                print(f'WARN: Thumbnail unavailable for {project.get("repo", "game")}: {str(exc)[:170]}', file=sys.stderr)
                valid_urls.append(url)
                previews.append('')
                dimensions.append(None)
                stats['fallback'] += 1
        project['screenshots'] = valid_urls
        project['screenshot_thumbnails'] = previews
        project['screenshot_dimensions'] = dimensions
        project.pop('_screenshot_revisions', None)

    # The published Pages artifact must never retain unreferenced thumbnails.
    referenced = {Path(p).name for project in projects for p in project.get('screenshot_thumbnails', []) if p}
    for file in destination.glob('*.webp'):
        if file.name not in referenced:
            file.unlink()
    if cache_root is not None:
        cached = cache_root / 'thumbnails'
        cached.mkdir(parents=True, exist_ok=True)
        for file in cached.glob('*.webp'):
            if file.stem not in next_manifest:
                file.unlink()
        cache_root.mkdir(parents=True, exist_ok=True)
        (cache_root / 'thumbnail-manifest.json').write_text(json.dumps({
            'schema_version': 2, 'entries': next_manifest,
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Screenshot thumbnails: {generated} generated, {cached} reused, '
          '{fallback} original-image fallbacks, {removed} removed / {total} inspected.'.format(**stats))
    return stats
