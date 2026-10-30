#!/usr/bin/env python3
"""Build a static public-GitHub-repository catalog. Python stdlib only.

Set GITHUB_OWNER to a user or organization (automatically supplied by Actions),
and optionally GITHUB_TOKEN for authenticated API limits.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen

from scripts.igdb import IGDBClient, cover_image, game_page
from scripts.game_links import GameLinksClient, verified_url
from scripts.youtube import YouTubeChannel, associate_videos, parse_channel
from scripts.thumbnails import generate_thumbnails

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.json"
OUTPUT = ROOT / "site" / "data" / "projects.json"
YOUTUBE_REPORT = ROOT / "reports" / "youtube-diagnostics.json"
API = "https://api.github.com"
COVER_PATHS = (
    "assets/cover.webp", "assets/cover.png", "assets/cover.jpg", "assets/cover.jpeg",
    "docs/cover.webp", "docs/cover.png", "docs/cover.jpg", "docs/cover.jpeg",
    "cover.webp", "cover.png", "cover.jpg", "cover.jpeg",
    "docs/images/cover.png", "docs/images/cover.jpg"
)
SCREENSHOT_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


class GitHubAPI:
    def __init__(self, token=None, retries=3):
        self.token = token
        self.retries = retries
        self.cache = {}

    def get(self, path, params=None, optional=False):
        url = (API + path if path.startswith("/") else path)
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        if url in self.cache:
            return self.cache[url]
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "patchwork-github-pages-indexer",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        for attempt in range(self.retries):
            try:
                with urlopen(Request(url, headers=headers), timeout=20) as response:
                    result = json.load(response)
                self.cache[url] = result
                return result
            except HTTPError as exc:
                if exc.code == 404 and optional:
                    return None
                if exc.code in (403, 429, 502, 503, 504) and attempt + 1 < self.retries:
                    pause = int(exc.headers.get("Retry-After", 0)) or (2 ** attempt)
                    time.sleep(min(pause, 10))
                    continue
                details = exc.read(300).decode("utf-8", errors="replace")
                raise RuntimeError(f"GitHub API returned HTTP {exc.code} for {url}: {details}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt + 1 < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"GitHub API request failed for {url}: {exc}") from exc
        return None


def owned_repos(api, owner):
    # The organization endpoint reliably lists repos belonging to org accounts.
    identity = api.get(f"/users/{quote(owner, safe='')}")
    is_org = isinstance(identity, dict) and identity.get("type") == "Organization"
    endpoint = (f"/orgs/{quote(owner, safe='')}/repos" if is_org
                else f"/users/{quote(owner, safe='')}/repos")
    output = []
    for page in range(1, 31):
        entries = api.get(endpoint, {
            "sort": "updated", "per_page": 100, "page": page,
            **({} if is_org else {"type": "owner"})
        })
        if not isinstance(entries, list):
            raise RuntimeError(f"Unexpected repository response for {owner}")
        output += entries
        if len(entries) < 100:
            break
    return output


def discover_repos(api, config, owner_fallback=""):
    discovery = config["discovery"]
    owners = discovery.get("owners") or ([owner_fallback] if owner_fallback else [])
    if not owners and not discovery.get("include_repositories") and not discovery.get("search_queries"):
        raise ValueError("No GitHub account configured. Set discovery.owners or GITHUB_OWNER.")
    selected = {}
    explicit = {name.casefold() for name in discovery.get("include_repositories", [])}
    excluded = {name.casefold() for name in discovery.get("exclude_repositories", [])}
    topics = {name.casefold() for name in discovery.get("include_topics_any", [])}
    phrases = [p.casefold() for p in discovery.get("include_description_matches", [])]

    def consider(repo, force=False):
        full_name = repo.get("full_name", "")
        if not full_name or full_name.casefold() in excluded or repo.get("private"):
            return
        if repo.get("fork") and not discovery.get("include_forks", False) and not force:
            return
        repo_topics = {str(t).casefold() for t in repo.get("topics") or []}
        info = " ".join((str(repo.get("name") or ""), str(repo.get("description") or ""))).casefold()
        if not force and not ((topics & repo_topics) or any(phrase in info for phrase in phrases)):
            return
        selected[full_name.casefold()] = repo

    for owner in owners:
        print(f"Scanning public repositories owned by {owner} ...")
        for repo in owned_repos(api, owner):
            consider(repo, force=(discovery.get("include_all_owner_repos", False)
                                  or repo.get("full_name", "").casefold() in explicit))

    for full_name in discovery.get("include_repositories", []):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", full_name, flags=re.ASCII):
            raise ValueError(f"Invalid include_repositories value: {full_name}")
        if full_name.casefold() not in selected:
            repo = api.get(f"/repos/{full_name}", optional=True)
            if repo:
                consider(repo, force=True)
            else:
                print(f"WARN: explicitly included repository not found: {full_name}", file=sys.stderr)

    for q in discovery.get("search_queries", []):
        print(f"Searching GitHub repositories: {q}")
        result = api.get("/search/repositories", {
            "q": q, "sort": "updated", "order": "desc",
            "per_page": min(100, max(1, int(discovery.get("search_results_per_query", 20))))
        })
        # Search queries are deliberate inclusion criteria; still respect exclusions/forks.
        for repo in result.get("items", []):
            consider(repo, force=True)

    repos = list(selected.values())
    repos.sort(key=lambda r: r.get("pushed_at") or r.get("updated_at") or "", reverse=True)
    return repos[:max(0, int(discovery.get("max_projects", 150)))]


# Detect systems through the seventh console generation (and retain modern
# platform labels supported by earlier versions). Alternative spellings are
# normalized with the same tokenizer used for repository names, so hyphens,
# underscores, parentheses and CamelCase are accepted. Specific consoles must
# match before generic prefixes such as Xbox, Wii, GB, and PC.
def slug_words(text):
    """Split repository slugs, including underscores and mixed-case names."""
    value = str(text or "")
    value = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", value)
    return re.findall(r"[A-Za-z0-9]+", value)


# Values become the displayed platform; strings are common repository aliases.
# Do not use broad ambiguous names such as '360', 'color' or '64' alone.
PLATFORM_VARIANTS = {
    # All arcade boards are deliberately grouped under the MAME label.
    # IGDB calls this hardware family "Arcade" (see scripts/igdb.py).
    "MAME": (
        "mame", "arcade", "arcade machine", "arcade board",
        "stv", "st-v", "st v", "sega st-v", "sega titan video", "sega titan video system",
        "cps1", "cps-1", "cps 1", "cps2", "cps-2", "cps 2", "cps3", "cps-3", "cps 3",
        "capcom play system", "capcom play system 2", "capcom play system 3",
        "naomi", "naomi 2", "sega naomi", "sega naomi 2", "atomiswave",
        "sega model 1", "sega model 2", "sega model 3", "model 1", "model 2", "model 3",
        "sega system 16", "sega system 32", "sega system16", "sega system32",
        "taito type x", "taito type-x", "taito f3", "taito f2",
        "triforce", "sega chihiro", "chihiro", "lindbergh", "sega lindbergh",
        "neo geo mvs", "neogeo mvs", "mvs", "konami gx", "namco system 22",
    ),
    # Seventh generation home consoles and handhelds
    "PS3": ("ps3", "playstation3", "PlayStation3", "playstation 3", "play station 3", "sony ps3"),
    "Xbox 360": ("xbox360", "xbox 360", "x-box 360", "xbox-360", "x box360", "x360", "xb360", "360 xbox"),
    "Wii": ("wii", "nintendo wii"),
    "PSP": ("psp", "playstation portable", "play station portable", "sony psp"),
    "NDS": ("nds", "nintendo ds", "nintendods", "nintendo dsi", "Nintendo-DSi", "nintendodsi", "ds", "dsi", "DSi"),
    # Sixth generation
    "PS2": ("ps2", "playstation2", "PlayStation2", "playstation 2", "play station 2"),
    "GameCube": ("gamecube", "game cube", "gcn", "ngc", "nintendo gamecube", "gc"),
    "Xbox": ("xbox", "x box", "original xbox", "xbox original", "og xbox"),
    "Dreamcast": ("dreamcast", "sega dreamcast", "dc"),
    "GBA": ("gba", "gameboy advance", "game boy advance", "gb advance", "gameboy micro", "game boy micro"),
    "N-Gage": ("n-gage", "ngage", "nokia ngage"),
    "GP32": ("gp32", "gamepark 32"),
    # Fifth generation
    "PS1": ("ps1", "psx", "psone", "ps one", "playstation", "play station", "playstation1", "PlayStation1", "playstation 1", "play station 1"),
    "Saturn": ("saturn", "sega saturn"),
    "N64": ("n64", "nintendo 64", "nintendo64"),
    "3DO": ("3do", "3do interactive multiplayer"),
    "Jaguar": ("atari jaguar", "jaguar", "jaguar cd"),
    "PC-FX": ("pcfx", "pc fx", "nec pc fx"),
    "GBC": ("gbc", "gameboy color", "game boy color", "gameboycolor"),
    "Virtual Boy": ("virtualboy", "virtual boy", "vb"),
    "Neo Geo Pocket Color": ("ngpc", "neo geo pocket color", "neogeopocketcolor"),
    "Neo Geo Pocket": ("ngp", "neo geo pocket", "neogeopocket"),
    "WonderSwan Color": ("wsc", "wonderswan color", "wonder swan color", "wonderswancolor"),
    "WonderSwan": ("ws", "wonderswan", "wonder swan"),
    # Fourth generation
    "SNES": ("snes", "super nintendo", "super nintendo entertainment system", "super famicom", "superfamicom", "sfc"),
    "Genesis": ("genesis", "mega drive", "megadrive", "sega genesis", "sega mega drive", "md"),
    "Sega CD": ("sega cd", "segacd", "mega cd", "megacd"),
    "32X": ("32x", "sega 32x", "mega 32x"),
    "PC Engine CD": ("pc engine cd", "pcengine cd", "pc engine cdrom", "pce cd", "pcecd", "turbografx cd", "tg cd"),
    "PC Engine": ("pc engine", "pcengine", "pce", "turbografx 16", "turbografx16", "TurboGrafx16", "tg16", "supergrafx"),
    "Neo Geo CD": ("neo geo cd", "neogeocd", "ngcd"),
    "Neo Geo": ("neo geo", "neogeo", "neo geo aes", "aes"),
    "GB": ("gameboy", "game boy", "gb", "dmg"),
    "Game Gear": ("gamegear", "game gear", "gg"),
    "Lynx": ("atari lynx", "lynx"),
    "CD-i": ("cd-i", "cdi", "philips cdi", "philips cd-i"),
    # Third generation and earlier
    "NES": ("nes", "nintendo entertainment system", "famicom", "family computer"),
    "Master System": ("master system", "mastersystem", "sms", "sega mark iii", "mark iii"),
    "SG-1000": ("sg1000", "sg 1000", "sega sg1000"),
    "Atari 7800": ("atari7800", "atari 7800", "a7800"),
    "Atari 5200": ("atari5200", "atari 5200", "a5200"),
    "Atari 2600": ("atari2600", "atari 2600", "a2600", "atari vcs"),
    "ColecoVision": ("colecovision", "coleco vision"),
    "Intellivision": ("intellivision", "mattel intellivision"),
    "Vectrex": ("vectrex", "mb vectrex"),
    "Odyssey 2": ("odyssey2", "odyssey 2", "videopac g7000"),
    "Odyssey": ("magnavox odyssey",),
    # Additional classic computers frequently used for game projects
    "MSX2": ("msx2", "msx 2"),
    "MSX": ("msx",),
    "PC-98": ("pc98", "pc 98", "pc9801", "pc 9801", "nec pc98"),
    "PC-88": ("pc88", "pc 88", "pc8801", "pc 8801", "nec pc88"),
    "X68000": ("x68000", "sharp x68000"),
    "FM Towns": ("fm towns", "fmtowns", "fm towns marty", "marty"),
    "Amiga": ("amiga", "commodore amiga"),
    "C64": ("c64", "commodore 64"),
    "DOS": ("ms dos", "msdos", "dos"),
    # Later consoles that were already recognized in the catalog
    "Wii U": ("wiiu", "wii u", "nintendo wii u"),
    "Switch": ("switch", "nintendo switch", "nsw"),
    "3DS": ("3ds", "nintendo 3ds", "n3ds"),
    "Vita": ("vita", "psvita", "ps vita", "playstation vita", "play station vita"),
    "PS4": ("ps4", "playstation 4", "playstation4"),
    "PS5": ("ps5", "playstation 5", "playstation5"),
    "Xbox One": ("xbox one", "xboxone", "x box one", "xb1"),
    "Xbox Series": ("xbox series", "xboxseries", "xbox series x", "xbox series s", "xsx", "xss"),
    "PC": ("windows", "win32", "win64", "pc"),
}

# A tuple is (token, token, ..., display_name), sorted longest-first. This
# avoids identifying 'Xbox 360' as 'Xbox' or 'PC Engine' as 'PC'.
PLATFORM_ALIASES = tuple(sorted(
    (tuple(token.casefold() for token in slug_words(variant)) + (platform,)
     for platform, variants in PLATFORM_VARIANTS.items() for variant in variants),
    key=lambda alias: -len(alias)
))


def platforms_in_text(text):
    """Identify every distinct console, using longest aliases without overlaps."""
    words = [w.casefold() for w in slug_words(text)]
    found = []
    index = 0
    while index < len(words):
        for *alias, platform in PLATFORM_ALIASES:
            if words[index:index + len(alias)] == alias:
                if platform not in found:
                    found.append(platform)
                index += len(alias)
                break
        else:
            index += 1
    return found


def platform_in_text(text):
    """Legacy single-platform helper, for older callers."""
    found = platforms_in_text(text)
    return found[0] if found else ""


def detect_platforms(repo):
    """Use name, then description, then topics; retain all platforms in the chosen source."""
    from_name = platforms_in_text(repo.get("name"))
    if from_name:
        return from_name
    from_description = platforms_in_text(repo.get("description"))
    if from_description:
        return from_description
    found = []
    for topic in repo.get("topics") or []:
        for platform in platforms_in_text(topic):
            if platform not in found:
                found.append(platform)
    return found


def detect_platform(repo):
    """Human-readable platform label, including multi-platform game patches."""
    return " / ".join(detect_platforms(repo)) or "Other"


def configured_platforms(override, detected):
    """Apply optional curated platform values without losing multi-platform metadata."""
    raw = override.get("platforms", override.get("platform"))
    if isinstance(raw, str):
        values = re.split(r"\s*/\s*|\s*[,;]\s*", raw)
    elif isinstance(raw, (list, tuple)):
        values = raw
    else:
        return detected
    found = []
    for value in values:
        if isinstance(value, str) and value.strip() and value.strip() != "Other":
            name = value.strip()
            # Normalize aliases in manually configured platform overrides too.
            key = tuple(word.casefold() for word in slug_words(name))
            for *alias, canonical in PLATFORM_ALIASES:
                if tuple(alias) == key:
                    name = canonical
                    break
            if name not in found:
                found.append(name)
    return found


# These are catalog metadata, not part of a game's actual title when they occur
# at the beginning or end of a repository slug.
TITLE_AFFIXES = (
    ("english", "fan", "translation"), ("english", "translation", "patch"),
    ("fan", "translation", "patch"), ("english", "translation"),
    ("fan", "translation"), ("translation", "patch"),
    ("english", "patch"), ("translation", "of"),
    ("translation", "for"), ("localization", "of"),
    ("localisation", "of"), ("translation",),
    ("localization",), ("localisation",), ("patch",),
    ("english",), ("eng",), ("en",), ("romhack",),
    ("wip",),
)


def display_title(repo, platform):
    """Infer a readable game title from the repo name without requiring assets/."""
    words = slug_words(repo.get("name") or "Untitled")
    original = words[:]
    # Remove only leading/trailing platform and translation qualifiers; do not
    # discard matching words inside a game's title (e.g. Saturn Bomberman).
    while words:
        lowered = [w.casefold() for w in words]
        candidates = [tuple(alias) for *alias, _ in PLATFORM_ALIASES] + list(TITLE_AFFIXES)
        candidates.sort(key=len, reverse=True)
        stripped = False
        for alias in candidates:
            n = len(alias)
            if lowered[:n] == list(alias) and len(words) > n:
                words = words[n:]
                stripped = True
                break
            if lowered[-n:] == list(alias) and len(words) > n:
                words = words[:-n]
                stripped = True
                break
        if not stripped:
            break
    words = words or original
    # Capitalize slug words without flattening CamelCase or roman numerals.
    # Keep small connecting words in normal English title style.
    small = {"a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "vs", "with"}
    acronyms = {"RPG", "JRPG", "HD", "DX", "EX", "II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII", "XIII", "XIV", "XV"}
    def tidy(word, index):
        if index > 0 and word.casefold() in small and word.islower():
            return word
        if word.islower() or (word.isupper() and len(word) > 3 and word not in acronyms):
            return word.capitalize()
        return word
    # Preserve established official spellings that separators/CamelCase alone
    # cannot infer. Users can still specify a title override in config.json.
    canonical = {"jailbreaker": "JailBreaker"}
    compact = "".join(w.casefold() for w in words)
    if compact in canonical:
        return canonical[compact]
    return " ".join(tidy(w, i) for i, w in enumerate(words))


def asset_url(repo, path):
    """Public raw file URL, with branch and path segments properly escaped."""
    bits = [repo["owner"]["login"], repo["name"], repo.get("default_branch") or "main"]
    return "https://raw.githubusercontent.com/" + "/".join(
        quote(x, safe="") for x in bits + path.split("/"))


def read_repo_text(api, repo, path, max_bytes=12_000):
    """Read optional repo text through the Contents API (no HTML scraping)."""
    owner, name = repo["owner"]["login"], repo["name"]
    item = api.get(f"/repos/{quote(owner)}/{quote(name)}/contents/" +
                   "/".join(quote(x) for x in path.split("/")),
                   {"ref": repo.get("default_branch") or "main"}, optional=True)
    if not isinstance(item, dict) or item.get("encoding") != "base64":
        return ""
    try:
        raw = base64.b64decode(item.get("content", ""), validate=False)
    except (ValueError, TypeError):
        return ""
    return raw[:max_bytes].decode("utf-8-sig", errors="replace").strip()


def valid_youtube_url(value):
    """Accept only ordinary YouTube video addresses with safe 11-char IDs."""
    line = next((line.strip() for line in str(value).splitlines()
                 if line.strip() and not line.lstrip().startswith("#")), "")
    if not line:
        return ""
    try:
        url = urlparse(line)
    except ValueError:
        return ""
    host = (url.hostname or "").lower()
    try:
        if url.scheme != "https" or url.username or url.password or url.port:
            return ""
    except ValueError:
        return ""
    video_id = ""
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
        if url.path == "/watch":
            video_id = parse_qs(url.query).get("v", [""])[0]
        elif url.path.startswith(("/shorts/", "/embed/", "/live/")):
            video_id = url.path.split("/")[2]
    elif host in ("youtu.be", "www.youtu.be"):
        video_id = url.path.strip("/")
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return "https://www.youtube.com/watch?v=" + video_id
    return ""


def parse_progress_status(text):
    """Accepted values for assets/status.txt, with a safe default."""
    value = str(text).strip().casefold()
    return "Paused" if value == "paused" else "In-Progress"


def find_media(api, repo):
    """Read gallery images, video link and optional prose from each repo's assets/."""
    owner, name = repo["owner"]["login"], repo["name"]
    branch = repo.get("default_branch") or "main"
    tree = api.get(f"/repos/{quote(owner)}/{quote(name)}/git/trees/{quote(branch, safe='')}",
                   {"recursive": 1}, optional=True)
    paths = {}
    if isinstance(tree, dict) and isinstance(tree.get("tree"), list):
        paths = {entry["path"].lower(): entry["path"] for entry in tree["tree"]
                 if entry.get("type") == "blob" and isinstance(entry.get("path"), str)}

    # A huge repository may return a truncated tree. Inspect assets/ independently.
    if not paths or (isinstance(tree, dict) and tree.get("truncated")):
        listing = api.get(f"/repos/{quote(owner)}/{quote(name)}/contents/assets",
                          {"ref": branch}, optional=True)
        if isinstance(listing, list):
            for entry in listing:
                if entry.get("type") == "file" and entry.get("path"):
                    paths[entry["path"].lower()] = entry["path"]

    cover_path = next((paths[p] for p in COVER_PATHS if p in paths), "")
    # Include any image anywhere under assets/, not just assets/screenshots/.
    # Existing docs/screenshots/ and screenshots/ are still supported.
    candidates = [path for lower, path in paths.items()
                  if lower.endswith(SCREENSHOT_EXTENSIONS) and
                  (lower.startswith("assets/") or lower.startswith("docs/screenshots/")
                   or lower.startswith("screenshots/")) and lower != cover_path.lower()]
    def natural_key(value):
        return [int(part) if part.isdigit() else part.casefold()
                for part in re.split(r"(\d+)", value)]
    candidates.sort(key=natural_key)
    shots = [asset_url(repo, path) for path in candidates[:32]]
    cover = asset_url(repo, cover_path) if cover_path else (shots[0] if shots else "")
    youtube = ""
    description = ""
    progress_status = "In-Progress"
    if "assets/youtube.txt" in paths:
        youtube = valid_youtube_url(read_repo_text(api, repo, paths["assets/youtube.txt"]))
    if "assets/description.txt" in paths:
        description = read_repo_text(api, repo, paths["assets/description.txt"], max_bytes=8_000)
    if "assets/status.txt" in paths:
        raw_status = read_repo_text(api, repo, paths["assets/status.txt"], max_bytes=128)
        progress_status = parse_progress_status(raw_status)
        if raw_status and raw_status.strip().casefold() not in {"paused", "in-progress"}:
            print(f"WARN: {repo['full_name']} assets/status.txt must be Paused or In-Progress; defaulting to In-Progress", file=sys.stderr)
    return cover, shots, youtube, description, progress_status


def find_art(api, repo):
    """Compatibility helper for callers interested only in covers and images."""
    cover, shots, *_ = find_media(api, repo)
    return cover, shots


def recent_release(api, repo):
    """Return availability, URL and tag of latest published GitHub Release.

    A published prerelease counts as a release; drafts do not.
    """
    owner, name = repo["owner"]["login"], repo["name"]
    releases = api.get(f"/repos/{quote(owner)}/{quote(name)}/releases", {"per_page": 30}, optional=True) or []
    published = [r for r in releases if isinstance(r, dict) and not r.get("draft")]
    if published:
        latest = max(enumerate(published), key=lambda pair:
                     (pair[1].get("published_at") or pair[1].get("created_at") or "", -pair[0]))[1]
        return True, latest.get("html_url", ""), latest.get("tag_name", "")
    return False, "", ""


def make_project(api, repo, overrides, igdb=None, igdb_settings=None, links=None):
    full_name = repo["full_name"]
    detected = detect_platforms(repo)
    # A repository cover wins. If only screenshots exist, IGDB should supply
    # the actual box art instead of treating a screenshot as a poster.
    override = {k.lower(): v for k, v in overrides.items()}.get(full_name.lower(), {})
    platforms = configured_platforms(override, detected)
    platform = " / ".join(platforms) or "Other"
    cover, screenshots, youtube_url, game_description, progress_status = find_media(api, repo)
    has_release, release_url, release_tag = recent_release(api, repo)
    settings = igdb_settings or {}
    igdb_result = None
    igdb_source = ""
    local_cover_exists = bool(cover) and cover not in screenshots
    needs_cover = not local_cover_exists and not override.get("cover_url")
    needs_summary = not game_description and not override.get("game_description") and settings.get("use_summaries", True)
    if igdb and (needs_cover or needs_summary or links):
        try:
            # A query override helps with official alternate titles. An ID
            # override resolves ambiguous or region-specific releases exactly.
            lookup_title = override.get("igdb_query") or override.get("title") or display_title(repo, platform)
            lookup_platform = platforms if len(platforms) > 1 else platform
            igdb_result = igdb.get_game(lookup_title, lookup_platform, override.get("igdb_id"))
            if igdb_result:
                igdb_source = game_page(igdb_result)
                if needs_cover:
                    cover = cover_image(igdb_result) or cover
        except RuntimeError as exc:
            print(f"WARN: IGDB unavailable for {full_name}: {exc}", file=sys.stderr)
    external_links = {"wikipedia_url": "", "mobygames_url": ""}
    if links:
        try:
            official_title = (override.get("igdb_query") or override.get("title")
                              or display_title(repo, platform))
            external_links = links.find(official_title, platforms, igdb_result)
        except RuntimeError as exc:
            print(f"WARN: external game links unavailable for {full_name}: {exc}", file=sys.stderr)
    # Prefer a verified Wikipedia introduction over IGDB for games without
    # manually authored or repository-authored descriptions. No paid APIs.
    wikipedia_summary = ""
    wiki_for_summary = (override.get("wikipedia_url", external_links["wikipedia_url"])
                        if "wikipedia_url" in override else external_links["wikipedia_url"])
    summary_names = tuple(dict.fromkeys(filter(None, (
        override.get("title") or display_title(repo, platform),
        override.get("igdb_query") or "",
        str((igdb_result or {}).get("name") or ""),
    ))))
    if (not game_description and not override.get("game_description") and
            not override.get("description") and links and wiki_for_summary):
        from scripts.game_links import verified_wikipedia_game_url
        wiki_for_summary = verified_wikipedia_game_url(wiki_for_summary, *summary_names)
        if wiki_for_summary and callable(getattr(links, "wikipedia_description", None)):
            try:
                wikipedia_summary = links.wikipedia_description(
                    wiki_for_summary, summary_names, platforms)
            except RuntimeError as exc:
                print(f"WARN: Wikipedia description unavailable for {full_name}: {exc}",
                      file=sys.stderr)
    igdb_summary = ((igdb_result or {}).get("summary") or "") if settings.get("use_summaries", True) else ""
    chosen_description = (game_description or wikipedia_summary or igdb_summary
                          or repo.get("description") or "No game description provided.")
    description_source = ("Wikipedia" if wikipedia_summary else
                          "IGDB" if igdb_summary and not game_description else "")
    chosen_description_source = (wiki_for_summary if wikipedia_summary else
                                 igdb_source if description_source == "IGDB" else "")
    # An actual published GitHub Release takes precedence over assets/status.txt.
    status = "Released" if has_release else progress_status
    project = {
        "id": full_name.lower(), "repo": full_name,
        "title": display_title(repo, platform),
        "description": repo.get("description") or "No repository description provided.",
        "platform": platform, "platforms": platforms, "status": status,
        "topics": repo.get("topics") or [],
        "owner": repo["owner"]["login"], "stars": repo.get("stargazers_count") or 0,
        "forks": repo.get("forks_count") or 0,
        "updated_at": repo.get("pushed_at") or repo.get("updated_at") or "",
        "github_url": repo.get("html_url") or "https://github.com/" + full_name,
        "homepage": repo.get("homepage") or "",
        "issue_url": (repo.get("html_url") or "https://github.com/" + full_name) + "/issues/new/choose" if repo.get("has_issues", True) else "",
        "release_url": release_url,
        "release_tag": release_tag,
        "has_release": has_release,
        "cover_url": cover, "screenshots": screenshots, "youtube_url": youtube_url,
        "igdb_title": (igdb_result or {}).get("name") or "",
        "youtube_match_titles": override.get("youtube_match_titles", []),
        "game_description": chosen_description,
        "description_source_url": chosen_description_source,
        "description_source": description_source,
        "igdb_url": igdb_source,
        "wikipedia_url": external_links["wikipedia_url"],
        "mobygames_url": external_links["mobygames_url"],
        "cover_source": ("repository" if local_cover_exists else ("igdb" if igdb_result and cover == cover_image(igdb_result) else ("screenshot" if cover else "placeholder"))),
        "featured": False, "demo": False
    }
    # Do not allow config overrides to falsify release detection or status.txt.
    allowed = {"title", "description", "game_description", "description_source_url",
               "cover_url", "screenshots", "youtube_url",
               "featured", "homepage"}
    project.update({k: v for k, v in override.items() if k in allowed})
    # Overrides must point to actual article/game URLs, not site searches.
    for field, service in (("wikipedia_url", "wikipedia"), ("mobygames_url", "mobygames")):
        if field in override:
            if service == "wikipedia":
                from scripts.game_links import verified_wikipedia_game_url
                project[field] = verified_wikipedia_game_url(override[field], project["title"],
                                                           str((igdb_result or {}).get("name") or ""))
            else:
                project[field] = verified_url(override[field], service)
    if override.get("cover_url"):
        project["cover_source"] = "configured"
    # An explicit per-game description override takes precedence over repo assets.
    if "description" in override and "game_description" not in override:
        project["game_description"] = override["description"]
    if "description" in override or "game_description" in override:
        # A manual override must never inherit stale attribution for the
        # automatically selected fallback description.
        if "description_source_url" not in override:
            project["description_source_url"] = ""
        project["description_source"] = ""
    return project


def index_youtube(projects, settings, env=None, report_path=None):
    """Index videos and save a public-metadata-only build diagnostic artifact.

    This file is not under site/ and is never uploaded to GitHub Pages.
    """
    from collections import Counter

    env = os.environ if env is None else env
    report_path = YOUTUBE_REPORT if report_path is None else Path(report_path)
    channel = (env.get("YOUTUBE_CHANNEL_ID") or settings.get("channel") or "").strip()
    key = (env.get("YOUTUBE_API_KEY") or "").strip()
    validated_channel = parse_channel(channel) if channel else None
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "not_started",
        "channel_configured": bool(channel),
        "channel": validated_channel[1] if validated_channel else ("[invalid channel format]" if channel else ""),
        "api_key_configured": bool(key),
        "method": "api" if key else "rss",
        "max_videos": settings.get("max_videos", 1000),
        "max_per_game": settings.get("max_per_game", 5),
        "videos_retrieved": 0,
        "videos_matched": 0,
        "outcomes": {},
        "projects": [],
        "videos": [],
    }
    try:
        if not settings.get("enabled", True):
            report["status"] = "disabled"
            report["message"] = "YouTube indexing is disabled in config.json."
        elif not channel:
            report["status"] = "missing_channel"
            report["message"] = ("YOUTUBE_CHANNEL_ID was not supplied. Configure an Actions variable "
                                 "or secret, or set youtube.channel in config.json.")
        else:
            client = YouTubeChannel(channel, key, settings.get("max_videos", 1000))
            print(f"YouTube: channel={validated_channel[1] if validated_channel else '[invalid channel format]'!r}, source={'Data API v3' if key else 'recent RSS feed'}, "
                  f"API key configured={'yes' if key else 'no'}")
            videos = client.videos()
            report["videos_retrieved"] = len(videos)
            associate_videos(projects, videos, settings.get("max_per_game", 5), diagnostics=report)
            report["videos_matched"] = sum(len(p.get("youtube_videos", [])) for p in projects)
            report["outcomes"] = dict(Counter(v["outcome"] for v in report["videos"]))
            report["status"] = "complete"
            print(f"YouTube: retrieved {len(videos)} videos; linked {report['videos_matched']} videos "
                  f"to {sum(bool(p.get('youtube_videos')) for p in projects)} / {len(projects)} games.")
            print("YouTube match outcomes: " + ", ".join(f"{k}={v}" for k, v in report["outcomes"].items()))
            if not videos:
                print("WARN: YouTube channel returned zero public videos. Check channel ID and API access.", file=sys.stderr)
            elif not report["videos_matched"]:
                print("WARN: YouTube videos loaded but none matched. Review titles and matching limits in the diagnostic artifact.", file=sys.stderr)
    except (RuntimeError, ValueError) as exc:
        report["status"] = "error"
        report["message"] = str(exc)
        print(f"WARN: YouTube channel lookup skipped: {exc}", file=sys.stderr)
    finally:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"YouTube diagnostics: {report_path.relative_to(ROOT) if report_path.is_relative_to(ROOT) else report_path}")
        if report["status"] in ("disabled", "missing_channel"):
            print(f"WARN: YouTube: {report['message']}", file=sys.stderr)
        summary = (env.get("GITHUB_STEP_SUMMARY") or "").strip()
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write("\n### YouTube channel indexing\n\n")
                handle.write(f"- Status: `{report['status']}`\n")
                handle.write(f"- Channel configured: {'Yes' if channel else 'No'}\n")
                handle.write(f"- YouTube API key configured: {'Yes' if key else 'No'}\n")
                handle.write(f"- Videos retrieved: {report['videos_retrieved']}\n")
                handle.write(f"- Videos linked: {report['videos_matched']}\n")
                handle.write("- Download the `youtube-diagnostics` artifact for video titles and unmatched reasons.\n")
    return report


def load_platform_colors():
    """Read the separately editable badge palette without changing discovery config."""
    file = ROOT / "platform-colors.json"
    if not file.exists():
        return {}
    data = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("platform-colors.json must be a JSON object")
    return data


def main():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    owner = os.getenv("GITHUB_OWNER", "").strip()
    api = GitHubAPI(token)
    repos = discover_repos(api, config, owner)
    igdb_settings = config.get("igdb", {})
    igdb = None
    if igdb_settings.get("enabled", True):
        client_id = os.getenv("IGDB_CLIENT_ID") or os.getenv("TWITCH_CLIENT_ID")
        client_secret = os.getenv("IGDB_CLIENT_SECRET") or os.getenv("TWITCH_CLIENT_SECRET")
        if client_id and client_secret:
            igdb = IGDBClient(client_id, client_secret)
            print("IGDB artwork lookup enabled.")
        else:
            print("IGDB artwork lookup skipped: set both IGDB_CLIENT_ID and IGDB_CLIENT_SECRET.")
    link_settings = config.get("external_links", {})
    links = GameLinksClient() if link_settings.get("enabled", True) else None
    projects = []
    for i, repo in enumerate(repos, 1):
        print(f"[{i}/{len(repos)}] Indexing {repo['full_name']}")
        try:
            projects.append(make_project(api, repo, config.get("overrides", {}), igdb, igdb_settings, links))
        except RuntimeError as exc:
            print(f"WARN: could not enrich {repo['full_name']}: {exc}", file=sys.stderr)
            # Keep the project even if additional metadata failed.
            fallback = GitHubAPI(token)
            fallback.get = lambda *args, **kwargs: []
            projects.append(make_project(fallback, repo, config.get("overrides", {}), igdb, igdb_settings, links))
    # Generate small local WebP previews, retaining original URLs for the viewer.
    generate_thumbnails(projects, ROOT / "site" / "assets" / "thumbnails", config.get("thumbnails", {}))
    # Index the channel once. An Actions-only report explains all exclusions.
    index_youtube(projects, config.get("youtube", {}))
    # Remove the internal matcher fields even if channel discovery is disabled.
    for project in projects:
        project.pop("igdb_title", None)
        project.pop("youtube_match_titles", None)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "demo": False, "site": config["site"],
        "platform_colors": load_platform_colors(),
        "projects": projects,
        "owners": config["discovery"].get("owners") or ([owner] if owner else [])
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(projects)} projects to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
