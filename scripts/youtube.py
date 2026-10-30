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

from scripts.igdb import title_tokens

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


MIN_TITLE_CHARS = 8  # Distinctive single-word game titles are valid matches.


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


def associate_videos(projects, videos, max_per_game=5, diagnostics=None):
    """Assign each video to one unambiguous strongest title match.

    Explicit per-repository youtube.txt remains separate and takes priority in
    the browser. The channel never overwrites that link.
    """
    max_per_game = max(0, min(20, int(max_per_game)))
    if diagnostics is not None:
        diagnostics["videos"] = []
        diagnostics["projects"] = []
        for project in projects:
            names = [project.get("title", ""), project.get("igdb_title", "")]
            names += [n for n in project.get("youtube_match_titles", []) if isinstance(n, str)]
            names = list(dict.fromkeys(n for n in names if n))
            diagnostics["projects"].append({
                "repo": project.get("repo", ""),
                "game": project.get("title", ""),
                "match_titles": names,
                "matching_limited": bool(names and not any(match_phrases(n) for n in names)),
                "explicit_video": bool(project.get("youtube_url")),
                "channel_matches": [],
            })
    for project in projects:
        project["youtube_videos"] = []
    for video in videos:
        video_id = str(video.get("id", ""))
        title = str(video.get("title", ""))
        outcome = "unmatched"
        matched_repo = ""
        if not VIDEO_ID.fullmatch(video_id):
            outcome = "invalid_video_id"
        else:
            ranked = []
            for project in projects:
                names = [project.get("title", ""), project.get("igdb_title", "")]
                names += [n for n in project.get("youtube_match_titles", []) if isinstance(n, str)]
                score = max((phrase_score(name, title) for name in names), default=0.0)
                if score:
                    ranked.append((score, len(title_tokens(project.get("title"))), project))
            ranked.sort(key=lambda item: item[:2], reverse=True)
            if not ranked:
                outcome = "no_title_match"
            elif len(ranked) > 1 and ranked[0][:2] == ranked[1][:2]:
                outcome = "ambiguous_match"
            else:
                project = ranked[0][2]
                matched_repo = str(project.get("repo") or project.get("title") or "")
                if len(project["youtube_videos"]) >= max_per_game:
                    outcome = "per_game_limit"
                elif video_id in str(project.get("youtube_url", "")):
                    outcome = "duplicate_explicit_video"
                elif any(video_id in previous["url"] for previous in project["youtube_videos"]):
                    outcome = "duplicate_channel_video"
                else:
                    project["youtube_videos"].append({"title": title, "url": f"https://www.youtube.com/watch?v={video_id}"})
                    outcome = "matched"
                    if diagnostics is not None:
                        for entry in diagnostics["projects"]:
                            if entry["repo"] == project.get("repo") and entry["game"] == project.get("title"):
                                entry["channel_matches"].append({"id": video_id, "title": title})
                                break
        if diagnostics is not None:
            diagnostics["videos"].append({"id": video_id, "title": title, "outcome": outcome,
                                          "game": matched_repo})
    for project in projects:
        # These names are internal matching aids and need not be published.
        project.pop("igdb_title", None)
        project.pop("youtube_match_titles", None)
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
