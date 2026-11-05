"""Fresh availability checks for YouTube links displayed in the catalog.

Never resurrects a disappeared video from saved metadata. The Data API is
preferred (batched groups of 50); oEmbed is a conservative keyless fallback.
An inconclusive result is not published by the build, but the scheduled
checker only requests a rebuild for a *confirmed* unavailable video.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

ID = re.compile(r'[A-Za-z0-9_-]{11}\Z')


def video_id(value):
    try:
        parts = urlsplit(str(value or ''))
        if parts.scheme != 'https' or parts.username or parts.password or parts.port:
            return ''
        host = (parts.hostname or '').lower()
        if host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
            if parts.path == '/watch':
                item = parse_qs(parts.query).get('v', [''])[0]
            elif parts.path.startswith(('/embed/', '/shorts/', '/live/')):
                item = parts.path.split('/')[2]
            else:
                return ''
        elif host in ('youtu.be', 'www.youtu.be'):
            item = parts.path.strip('/')
        else:
            return ''
        return item if ID.fullmatch(item) else ''
    except (ValueError, IndexError):
        return ''


def _oembed_status(video):
    url = 'https://www.youtube.com/oembed?' + urlencode({
        'url': 'https://www.youtube.com/watch?v=' + video, 'format': 'json'})
    try:
        with urlopen(Request(url, headers={'User-Agent': 'game-catalog-media-check/1.0'}), timeout=6) as res:
            data = json.load(res)
        return True if isinstance(data, dict) and data.get('title') else None
    except HTTPError as exc:
        if exc.code in (401, 403, 404, 410):
            return False
        return None
    except (URLError, TimeoutError, OSError, ValueError):
        return None


def check_videos(ids, api_key='', workers=10):
    """Map video IDs to True (public), False (unavailable), None (unknown).

    A video listed as not embeddable is unavailable *in this site's viewer*.
    This check is repeated for referenced videos, not supplied by a cache.
    """
    unique = list(dict.fromkeys(str(value) for value in ids if ID.fullmatch(str(value))))
    if not unique:
        return {}
    if not api_key:
        with ThreadPoolExecutor(max_workers=max(1, min(12, workers))) as pool:
            return dict(zip(unique, pool.map(_oembed_status, unique)))
    result = {}
    for start in range(0, len(unique), 50):
        group = unique[start:start + 50]
        url = 'https://www.googleapis.com/youtube/v3/videos?' + urlencode({
            'part': 'status', 'id': ','.join(group), 'key': api_key})
        try:
            with urlopen(Request(url, headers={'User-Agent': 'game-catalog-media-check/1.0'}), timeout=15) as res:
                response = json.load(res)
            if not isinstance(response, dict) or not isinstance(response.get('items'), list):
                raise ValueError('Missing items list')
            available = set()
            for item in response['items']:
                status = item.get('status') or {}
                if (item.get('id') in group and status.get('privacyStatus') in ('public', 'unlisted')
                        and status.get('embeddable') is not False
                        and status.get('uploadStatus', 'processed') not in ('deleted', 'failed', 'rejected')):
                    available.add(item['id'])
            result.update({video: video in available for video in group})
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            # API outages are not proof that a video has been deleted.
            result.update({video: None for video in group})
    return result


def remove_unavailable_videos(projects, api_key='', status_provider=check_videos):
    """Validate both youtube.txt/override URLs and channel-matched videos.

    No stale cached video match is used. Fail closed for unverified references;
    the next successful build can restore them if a provider is temporarily down.
    """
    identifiers = []
    for project in projects:
        for url in project.get('youtube_urls') or []:
            identifiers.append(video_id(url))
        for entry in project.get('youtube_videos') or []:
            identifiers.append(video_id(entry.get('url')))
    results = status_provider([v for v in identifiers if v], api_key)
    removed = unknown = 0
    for project in projects:
        explicit = project.get('youtube_urls') or []
        good = []
        for url in explicit:
            id_ = video_id(url)
            if id_ and results.get(id_) is True:
                good.append(url)
            elif url:
                removed += results.get(id_) is False
                unknown += results.get(id_) is not False
        project['youtube_urls'] = good
        videos = []
        for item in project.get('youtube_videos') or []:
            id_ = video_id(item.get('url'))
            if id_ and results.get(id_) is True:
                videos.append(item)
            else:
                removed += results.get(id_) is False
                unknown += results.get(id_) is not False
        project['youtube_videos'] = videos
    return {'checked': len(results), 'removed': removed, 'unverified': unknown}
