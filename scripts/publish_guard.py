"""Fail closed if an unexpected file would enter the public Pages artifact.

Only the rendered site is public. In particular, private config checkouts,
private cache state, raw Markdown, credentials and diagnostic files must never
be included in the Pages payload. This validates the exact folder uploaded
by upload-pages-artifact, immediately before the upload step.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT_FILES = {
    '.nojekyll', 'index.html', 'about.html', 'app.js', 'about.js',
    'styles.css', 'feed.xml',
}
DATA_FILES = {'projects.json', 'watch-state.json'}
ASSET_FILES = {
    'default-icon.svg', 'logo.png', 'favicon.png',
    'theme.css',
    'discord.svg', 'discord_light.svg', 'discord_dark.svg',
    'bluesky.svg', 'bluesky_light.svg', 'bluesky_dark.svg',
    'github.svg', 'github_light.svg', 'github_dark.svg',
    'rss.svg', 'rss_light.svg', 'rss_dark.svg',
    'kofi.svg', 'kofi_light.svg', 'kofi_dark.svg',
}
DIRECTORIES = {'data', 'assets', 'assets/thumbnails'}
THUMB = re.compile(r'[0-9a-f]{24}\.webp\Z')


def verify_publishable_site(root):
    """Return file count or raise before any public artifact upload."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Published site root must be a real directory')
    for required in ('index.html', 'about.html', 'app.js', 'styles.css'):
        if not (root / required).is_file() or (root / required).is_symlink():
            raise ValueError(f'Missing required public site file: {required}')
    files = 0
    for item in root.rglob('*'):
        rel = item.relative_to(root).as_posix()
        if item.is_symlink():
            raise ValueError(f'Symlink in public Pages payload: {rel}')
        if item.is_dir():
            if rel not in DIRECTORIES:
                raise ValueError(f'Unexpected directory in public Pages payload: {rel}')
            continue
        if not item.is_file():
            raise ValueError(f'Unexpected entry in public Pages payload: {rel}')
        parts = item.relative_to(root).parts
        permitted = (
            (len(parts) == 1 and rel in ROOT_FILES)
            or (len(parts) == 2 and parts[0] == 'data' and parts[1] in DATA_FILES)
            or (len(parts) == 2 and parts[0] == 'assets' and parts[1] in ASSET_FILES)
            or (len(parts) == 3 and parts[:2] == ('assets', 'thumbnails')
                and bool(THUMB.fullmatch(parts[2])))
        )
        if not permitted:
            raise ValueError(f'Unexpected file in public Pages payload: {rel}')
        files += 1
    return files


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit('Usage: python -m scripts.publish_guard site')
    try:
        count = verify_publishable_site(argv[0])
    except ValueError as exc:
        print(f'ERROR: Pages upload blocked: {exc}', file=sys.stderr)
        return 1
    print(f'Pages payload verified: {count} files; no raw private configuration or cache files')
    return 0


if __name__ == '__main__':
    sys.exit(main())
