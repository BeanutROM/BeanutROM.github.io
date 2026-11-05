"""Durable private build-cache location and RSS history, never an Actions artifact."""
from __future__ import annotations
import os
import shutil
from pathlib import Path


def cache_directory(env=None):
    env = os.environ if env is None else env
    raw = str(env.get('CATALOG_CACHE_DIR', '')).strip()
    if not raw:
        return None
    path = Path(raw).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_history(cache_root, feed_path, projects_path):
    if cache_root is None:
        return
    target = Path(cache_root) / 'rss'
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(feed_path, target / 'feed.xml')
    # Status transitions need the previous published project states.
    shutil.copyfile(projects_path, target / 'projects.json')
