"""Optional build-time YouTube channel discovery. Uses public YouTube APIs/feeds.

The API key remains in the GitHub Actions process and is never written to Pages.
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from scripts.igdb import PLATFORM_NAMES, normalize, title_tokens

API_ROOT = "https://www.googleapis.com/youtube/v3/"
FEED_ROOT = "https://www.youtube.com/feeds/videos.xml"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
HANDLE = re.compile(r"@[A-Za-z0-9_.-]{3,30}\Z")
# A game name followed by an enumerated installment should not match another game.
SEQUELS = {"ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii",
           "remastered", "remaster", "remake", "sequel", "spinoff", "spin", "returns"}


def parse_channel(value):
    """Return ('id'|'handle', value), rejecting unknown URL shapes."""
    value = str(value or "").strip()
    if value.startswith("https://"):
        url = urlsplit(value)
        if url.hostname not in ("youtube.com", "www.youtube.com", "m.youtube.com") or url.username or url.password or url.port:
            return None
        pieces = [segment for segment in url.path.split("/") if segment]
        if len(pieces) == 2 and pieces[0] == "channel":
            value = pieces[1]
        elif pieces and pieces[0].startswith("@"):
            value = pieces[0]
        else:
            return None
    if CHANNEL_ID.fullmatch(value):
        return "id", value
    if HANDLE.fullmatch(value):
        return "handle", value
    return None


MIN_TITLE_CHARS = 8  # Single words at or above this size can match by name alone.
SHORT_TITLE_CHARS = 3  # Shorter names require console + translation context.

# Use the canonical IGDB platform aliases, rather than hardcoding PSX-only checks.
# Additional compact spellings occur frequently in video names.
EXTRA_PLATFORM_ALIASES = {
    "PS1": ("playstation 1", "playstation1"),
    "PS2": ("playstation2",),
    "PS3": ("playstation3",),
    "Xbox 360": ("xbox360",),
    "GameCube": ("nintendo game cube",),
    "PC-FX": ("pcfx",),
    "MAME": ("mame", "st-v", "stv", "cps1", "cps2", "cps3", "naomi", "atomiswave"),
}
PLATFORM_PHRASES = tuple(sorted(
    {(tuple(normalize(alias).split()), platform)
     for platform, aliases in PLATFORM_NAMES.items()
     for alias in (*aliases, platform, *EXTRA_PLATFORM_ALIASES.get(platform, ()))
     if normalize(alias)}, key=lambda entry: -len(entry[0])
))

# A short/common game name is unsafe on its own. A video must explicitly be
# about an English translation/patch, not merely contain the word "English".
TRANSLATION_CONTEXT = re.compile(
    r"\b(?:english|fan)\s+(?:translation|patch|locali[sz]ation)\b"
    r"|\b(?:translated|translation\s+patch)\b", re.IGNORECASE
)


def mentioned_platforms(text):
    """Recognize console aliases as complete words, with longer names first."""
    words = normalize(text).split()
    platforms = set()
    i = 0
    while i < len(words):
        for phrase, platform in PLATFORM_PHRASES:
            if words[i:i + len(phrase)] == list(phrase):
                platforms.add(platform)
                i += len(phrase)
                break
        else:
            i += 1
    return platforms


def project_platforms(project):
    """Read the platforms declared in the generated project data."""
    return {platform
            for item in (project.get("platforms") or [])
            for platform in mentioned_platforms(item)}


def short_title_eligible(game, project):
    tokens = title_tokens(game)
    return (len(tokens) == 1 and SHORT_TITLE_CHARS <= len(tokens[0]) < MIN_TITLE_CHARS
            and bool(project_platforms(project)))


def contextual_short_score(game, video, project):
    """Match short titles only with explicit console and translation evidence.

    The name must start the video title, or immediately follow a console prefix.
    This avoids accepting an unrelated description that happens to mention a
    short/common word elsewhere in the title.
    """
    if not short_title_eligible(game, project):
        return 0.0
    if not TRANSLATION_CONTEXT.search(normalize(video)):
        return 0.0
    platforms = project_platforms(project)
    if not platforms.intersection(mentioned_platforms(video)):
        return 0.0
    game_token = title_tokens(game)[0]
    words = title_tokens(video)
    for i, word in enumerate(words):
        if word != game_token:
            continue
        following = words[i + 1:]
        if following and (following[0] in SEQUELS or following[0].isdigit()):
            continue
        if i == 0:
            return 0.91
        # Only the known platform may precede a short title; do not match it
        # in arbitrary sentences or video descriptions.
        prefix = " ".join(words[:i])
        if platforms.intersection(mentioned_platforms(prefix)):
            if normalize(prefix) in {normalize(alias)
                                     for platform in platforms
                                     for alias in (*PLATFORM_NAMES.get(platform, (platform,)), platform,
                                                   *EXTRA_PLATFORM_ALIASES.get(platform, ()))}:
                return 0.88
    return 0.0


def match_phrases(game):
    """Tokenized title forms, including joined spellings such as JailBreaker."""
    tokens = title_tokens(game)
    if not tokens or len("".join(tokens)) < MIN_TITLE_CHARS:
        return ()
    options = [tokens]
    if len(tokens) > 1:
        options.append(("".join(tokens),))
    return tuple(options)


def phrase_score(game, video):
    """Score distinct titles using whole tokens and joined or split compounds.

    Allows distinctive single-word game names, but not short generic tokens.
    Sequel and remake suffixes immediately after the title are rejected.
    """
    tokens = title_tokens(video)
    # Treat a two-word compound in the video as an optional joined token.
    # This handles both JailBreaker -> Jail Breaker and the reverse.
    hay_variants = [tokens]
    hay_variants.extend(
        tokens[:i] + (tokens[i] + tokens[i + 1],) + tokens[i + 2:]
        for i in range(len(tokens) - 1)
        if tokens[i] not in SEQUELS and tokens[i + 1] not in SEQUELS
        and not tokens[i].isdigit() and not tokens[i + 1].isdigit()
    )
    matches = []
    for hay in hay_variants:
        for needle in match_phrases(game):
            if len(hay) < len(needle):
                continue
            if needle == hay:
                matches.append(1.0)
                continue
            for start in range(len(hay) - len(needle) + 1):
                if hay[start:start + len(needle)] != needle:
                    continue
                after = hay[start + len(needle):]
                if after and (after[0] in SEQUELS or after[0].isdigit()):
                    continue
                if start == 0:
                    matches.append(0.92 if after else 1.0)
                elif start + len(needle) == len(hay):
                    matches.append(0.90)
                else:
                    matches.append(0.80)
    return max(matches, default=0.0)


def associate_videos(projects, videos, max_per_game=5):
    """Assign each video to one unambiguous strongest title match.

    Explicit per-repository youtube.txt links remain separate and are displayed
    before channel discoveries. The channel never overwrites those links.
    """
    max_per_game = max(0, min(20, int(max_per_game)))
    for project in projects:
        project["youtube_videos"] = []
    for video in videos:
        video_id = str(video.get("id", ""))
        title = str(video.get("title", ""))
        if not VIDEO_ID.fullmatch(video_id):
            continue
        ranked = []
        for project in projects:
            names = [project.get("title", ""), project.get("igdb_title", "")]
            names += [n for n in project.get("youtube_match_titles", []) if isinstance(n, str)]
            score = max((max(phrase_score(name, title), contextual_short_score(name, title, project))
                         for name in names), default=0.0)
            if score:
                ranked.append((score, len(title_tokens(project.get("title"))), project))
        ranked.sort(key=lambda item: item[:2], reverse=True)
        if not ranked or (len(ranked) > 1 and ranked[0][:2] == ranked[1][:2]):
            continue
        project = ranked[0][2]
        if len(project["youtube_videos"]) >= max_per_game:
            continue
        if video_id in {
            url.rsplit("v=", 1)[-1]
            for url in (project.get("youtube_urls") or [])
            if isinstance(url, str) and "v=" in url
        }:
            continue
        if any(video_id in previous["url"] for previous in project["youtube_videos"]):
            continue
        project["youtube_videos"].append({"title": title, "url": f"https://www.youtube.com/watch?v={video_id}"})
    return projects


class YouTubeChannel:
    def __init__(self, channel, api_key="", max_videos=1000):
        self.channel = parse_channel(channel)
        if self.channel is None:
            raise ValueError("YOUTUBE_CHANNEL_ID must be a channel ID, @handle or supported channel URL")
        self.key = str(api_key or "").strip()
        self.max_videos = max(1, min(5000, int(max_videos)))

    def _request(self, url, params):
        # Never include API keys in errors or public output.
        request = Request(url + "?" + urlencode(params), headers={"User-Agent": "game-catalog-builder"})
        for attempt in range(3):
            try:
                with urlopen(request, timeout=20) as response:
                    return response.read()
            except HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                # Report API error codes, not raw server messages or secret-bearing URLs.
                # Google provides structured, non-sensitive reason identifiers.
                reason = ""
                try:
                    payload = json.loads(exc.read(8192))
                    failure = payload.get("error") or {}
                    errors = failure.get("errors") or []
                    if errors and isinstance(errors[0], dict):
                        reason = str(errors[0].get("reason") or "")
                    if not reason:
                        reason = str(failure.get("status") or "")
                    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", reason):
                        reason = ""
                except (ValueError, TypeError, AttributeError, OSError):
                    pass
                raise RuntimeError(f"YouTube returned HTTP {exc.code}" +
                                   (f" ({reason})" if reason else "")) from None
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"YouTube request failed ({type(exc).__name__})") from None

    def _json(self, resource, **params):
        try:
            data = json.loads(self._request(API_ROOT + resource, {**params, "key": self.key}))
            if not isinstance(data, dict):
                raise ValueError("Invalid response")
            return data
        except ValueError:
            raise RuntimeError("YouTube returned invalid JSON") from None

    def videos(self):
        if not self.key:
            if self.channel[0] != "id":
                raise RuntimeError("YouTube channel @handles require YOUTUBE_API_KEY; use a UC... channel ID for the RSS fallback")
            try:
                root = ET.fromstring(self._request(FEED_ROOT, {"channel_id": self.channel[1]}))
            except ET.ParseError:
                raise RuntimeError("YouTube RSS returned invalid XML") from None
            ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
            output = []
            for entry in root.findall("a:entry", ns):
                video_id = (entry.findtext("yt:videoId", "", ns) or "").strip()
                title = (entry.findtext("a:title", "", ns) or "").strip()
                if VIDEO_ID.fullmatch(video_id) and title:
                    output.append({"id": video_id, "title": title})
            return output[:self.max_videos]
        selector = {self.channel[0] == "id" and "id" or "forHandle": self.channel[1]}
        data = self._json("channels", part="contentDetails", **selector)
        entries = data.get("items") or []
        playlist = ((entries[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") if entries else ""
        if not isinstance(playlist, str) or not playlist:
            raise RuntimeError("YouTube channel has no accessible uploads playlist")
        output, seen, token = [], set(), ""
        while len(output) < self.max_videos:
            data = self._json("playlistItems", part="snippet", playlistId=playlist,
                              maxResults=min(50, self.max_videos - len(output)), **({"pageToken": token} if token else {}))
            for entry in data.get("items") or []:
                snippet = entry.get("snippet") or {}
                video_id = str((snippet.get("resourceId") or {}).get("videoId") or "")
                title = str(snippet.get("title") or "").strip()
                if (VIDEO_ID.fullmatch(video_id) and video_id not in seen
                        and title and title not in ("Private video", "Deleted video")):
                    output.append({"id": video_id, "title": title})
                    seen.add(video_id)
            next_token = str(data.get("nextPageToken") or "")
            if not next_token or next_token == token:
                break
            token = next_token
        return output[:self.max_videos]
