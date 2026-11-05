#!/usr/bin/env python3
"""Build a static public-GitHub-repository catalog. Python stdlib only.

Set GITHUB_OWNER to a user or organization (automatically supplied by Actions),
and optionally GITHUB_TOKEN for authenticated API limits.
"""
from __future__ import annotations

import base64
import hashlib
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
from scripts.rss_feed import build_rss_feed
from scripts.cache_state import cache_directory, save_history
from scripts.media_validation import remove_unavailable_videos
from scripts.branding_svg import validate_svg

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.json"
OUTPUT = ROOT / "site" / "data" / "projects.json"
API = "https://api.github.com"
COVER_PATHS = (
    "assets/cover.webp", "assets/cover.png", "assets/cover.jpg", "assets/cover.jpeg",
    "docs/cover.webp", "docs/cover.png", "docs/cover.jpg", "docs/cover.jpeg",
    "cover.webp", "cover.png", "cover.jpg", "cover.jpeg",
    "docs/images/cover.png", "docs/images/cover.jpg"
)
SCREENSHOT_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

# Update-date event bitmask. Fallback: first commit, then repository creation.
UPDATE_RELEASES = 1
UPDATE_STATUS = 2
UPDATE_ASSETS = 4
UPDATE_ANY_COMMIT = 8
DEFAULT_UPDATE_FLAGS = UPDATE_RELEASES | UPDATE_STATUS
ALL_UPDATE_FLAGS = UPDATE_RELEASES | UPDATE_STATUS | UPDATE_ASSETS | UPDATE_ANY_COMMIT



def _json_object(value, source):
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source} must contain valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{source} must contain a JSON object")
    return parsed


def private_config_directory(env=None):
    """Local checkout of the optional private configuration repository."""
    env = os.environ if env is None else env
    raw = str(env.get("CATALOG_PRIVATE_CONFIG_DIR", "")).strip()
    return Path(raw).resolve() if raw else None


def private_config_json(filename, env=None):
    private = private_config_directory(env)
    if private is None:
        return None
    if not private.is_dir():
        raise ValueError(f"CATALOG_PRIVATE_CONFIG_DIR does not exist: {private}")
    path = private / filename
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"Private configuration path is not a file: {filename}")
    return _json_object(path.read_text(encoding="utf-8"), filename)


PRIVATE_CONFIG_FILES = (
    "config.json", "branding.json", "platform-colors.json",
    "assets/logo.png", "assets/favicon.png", "theme.css", "about.md",
    *(f"assets/{service}{suffix}.svg" for service in ("rss", "github", "discord", "bluesky", "kofi")
      for suffix in ("", "_light", "_dark")),
)


def private_config_fingerprint(env=None):
    """Opaque checksum for detecting changes to supported private config files."""
    private = private_config_directory(env)
    if private is None:
        return ""
    if not private.is_dir():
        raise ValueError(f"CATALOG_PRIVATE_CONFIG_DIR does not exist: {private}")
    digest = hashlib.sha256()
    for filename in PRIVATE_CONFIG_FILES:
        path = private / filename
        if path.is_file():
            digest.update(filename.encode('ascii') + b'\0')
            digest.update(path.read_bytes())
            digest.update(b'\0')
    return digest.hexdigest()


def load_config(env=None):
    """Merge private config.json over the non-identifying public defaults."""
    env = os.environ if env is None else env
    config = _json_object(CONFIG.read_text(encoding="utf-8"), "public config.json")
    private = private_config_json("config.json", env)
    if private is not None:
        # Keep a single private config.json with the same section names as the
        # public config. Only explicitly supplied keys override public defaults.
        # Site branding and social URLs are configured only in branding.json.
        unknown = set(private) - set(config)
        if unknown:
            raise ValueError("Unknown private config.json sections: " + ", ".join(sorted(unknown)))
        for section, values in private.items():
            if not isinstance(values, dict) or not isinstance(config.get(section), dict):
                raise ValueError(f"Private config.json {section} must be an object")
            extra = set(values) - set(config[section]) if section != "overrides" else set()
            if extra:
                raise ValueError(f"Unknown private config.json {section} keys: " + ", ".join(sorted(extra)))
            if section == "overrides" and not all(isinstance(k, str) and isinstance(v, dict)
                                                    for k, v in values.items()):
                raise ValueError("Private config.json overrides must map OWNER/REPO to objects")
            config[section].update(values)
    discovery = config.setdefault("discovery", {})
    if not isinstance(discovery.get("owners", []), list) or not all(
        isinstance(x, str) for x in discovery.get("owners", [])
    ):
        raise ValueError("config.json discovery.owners must be an array of usernames")
    current_repo = env.get("GITHUB_REPOSITORY", "").strip()
    if current_repo:
        exclusions = discovery.setdefault("exclude_repositories", [])
        if current_repo.casefold() not in {str(v).casefold() for v in exclusions}:
            exclusions.append(current_repo)
    return config


def load_site_settings(config, env=None):
    """Site text comes from optional private config files or Actions JSON."""
    env = os.environ if env is None else env
    site = dict(config.get("site") or {})
    private = private_config_directory(env)
    if private is not None:
        manifest = private / 'branding.json'
        if manifest.is_file():
            values = _json_object(manifest.read_text(encoding='utf-8'), 'branding.json')
            branded_site = values.get('site') or {}
            if not isinstance(branded_site, dict):
                raise ValueError('branding.json site must be a JSON object')
            site.update(branded_site)
    if env.get('CATALOG_SITE_JSON', '').strip():
        site.update(_json_object(env['CATALOG_SITE_JSON'], 'CATALOG_SITE_JSON'))
    site.setdefault('name', 'Game Catalog')
    site.setdefault('tagline', 'Game projects and releases')
    # Images never need to exist in the source repository. Published assets
    # are copied from a private checkout during the build.
    # Social URLs and Ko-fi text are supplied by branding.json.
    if private is not None and (private / 'assets').is_symlink():
        raise ValueError('Private branding assets directory must not be a symlink')
    image_names = {'logo.png': 'logo_url', 'favicon.png': 'favicon_url'}
    for filename, key in image_names.items():
        target = ROOT / 'site' / 'assets' / filename
        source = private / 'assets' / filename if private is not None else None
        if source is not None and source.is_symlink():
            raise ValueError(f"Private branding image must not be a symlink: {filename}")
        if source is not None and source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            site[key] = 'assets/' + filename
        else:
            target.unlink(missing_ok=True)
            site.pop(key, None)
    theme = private / 'theme.css' if private is not None else None
    theme_target = ROOT / 'site' / 'assets' / 'theme.css'
    if theme is not None and theme.is_symlink():
        raise ValueError('Private branding theme must not be a symlink')
    if theme is not None and theme.is_file():
        theme_target.parent.mkdir(parents=True, exist_ok=True)
        theme_target.write_bytes(theme.read_bytes())
        site['theme_url'] = 'assets/theme.css'
    else:
        theme_target.unlink(missing_ok=True)
        site.pop('theme_url', None)
    # SVG icons must be self-contained and are taken only from assets/.
    # Theme variants independently fall back to the base SVG, then to text.
    for service in ('rss', 'github', 'discord', 'bluesky', 'kofi'):
        for suffix in ('', '_light', '_dark'):
            filename = f'{service}{suffix}.svg'
            key = f'{service}_icon{suffix}_url'
            target = ROOT / 'site' / 'assets' / filename
            source = private / 'assets' / filename if private is not None else None
            if source is not None and source.is_symlink():
                raise ValueError(f"Private branding SVG must not be a symlink: {filename}")
            if source is not None and source.is_file():
                data = source.read_bytes()
                validate_svg(data, filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                site[key] = 'assets/' + filename
            else:
                target.unlink(missing_ok=True)
                site.pop(key, None)
    site.setdefault('logo_url', 'assets/default-icon.svg')
    site.setdefault('favicon_url', 'assets/default-icon.svg')
    return site


ABOUT_PAGE = ROOT / "site" / "about.html"
ABOUT_START = "<!-- BEGIN PRIVATE ABOUT CONTENT -->"
ABOUT_END = "<!-- END PRIVATE ABOUT CONTENT -->"


def render_about_page(env=None, output_path=None):
    """Render optional private about.md into the public static About page.

    No private checkout or no about.md means an empty article. The markers
    allow repeatable builds and ensure that removing about.md clears old text.
    Raw HTML from Markdown is escaped; only the rendered article is published.
    """
    page = Path(output_path) if output_path is not None else ABOUT_PAGE
    template = page.read_text(encoding="utf-8")
    if template.count(ABOUT_START) != 1 or template.count(ABOUT_END) != 1:
        raise ValueError("site/about.html is missing its About content markers")
    start = template.index(ABOUT_START) + len(ABOUT_START)
    end = template.index(ABOUT_END)
    if end < start:
        raise ValueError("site/about.html has invalid About content markers")

    rendered = ""
    private = private_config_directory(env)
    if private is not None:
        if not private.is_dir():
            raise ValueError(f"CATALOG_PRIVATE_CONFIG_DIR does not exist: {private}")
        markdown_path = private / "about.md"
        if markdown_path.exists():
            if not markdown_path.is_file():
                raise ValueError("Private about.md must be a file")
            if markdown_path.stat().st_size > 1_048_576:
                raise ValueError("Private about.md cannot exceed 1 MiB")
            markdown_text = markdown_path.read_text(encoding="utf-8")
            if markdown_text.strip():
                try:
                    import mistune
                except ImportError as exc:
                    raise RuntimeError("Markdown rendering requires: pip install -r requirements.txt") from exc
                parser = mistune.create_markdown(
                    escape=True, plugins=["strikethrough", "table", "task_lists", "url"]
                )
                rendered = parser(markdown_text).rstrip()

    replacement = ("\n" + rendered + "\n        ") if rendered else "\n        "
    page.write_text(template[:start] + replacement + template[end:], encoding="utf-8")
    return bool(rendered)


def parse_update_flags(config):
    """Validate the numeric OR mask from config.json, defaulting to releases/status."""
    updates = config.get("updates", {})
    if not isinstance(updates, dict):
        raise ValueError("updates must be a JSON object")
    flags = updates.get("flags", DEFAULT_UPDATE_FLAGS)
    if type(flags) is not int or not 0 <= flags <= ALL_UPDATE_FLAGS:
        raise ValueError("updates.flags must be an integer bitmask from 0 to 15")
    return flags


class GitHubAPI:
    def __init__(self, token=None, retries=3):
        self.token = token
        self.retries = retries
        self.cache = {}
        self.link_headers = {}

    def pagination_link(self, path, params, rel="last"):
        """Look up a pagination URL saved by a previous get() call."""
        url = API + path if path.startswith("/") else path
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        links = self.link_headers.get(url, "")
        match = re.search(r'<([^>]+)>\s*;\s*rel="' + re.escape(rel) + r'"', links)
        if not match:
            return ""
        candidate = urlparse(match.group(1))
        return match.group(1) if candidate.scheme == "https" and candidate.netloc == "api.github.com" else ""

    def get(self, path, params=None, optional=False):
        url = (API + path if path.startswith("/") else path)
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        if url in self.cache:
            return self.cache[url]
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "game-catalog-indexer",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        for attempt in range(self.retries):
            try:
                with urlopen(Request(url, headers=headers), timeout=20) as response:
                    result = json.load(response)
                    self.link_headers[url] = response.headers.get("Link", "")
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


def parse_youtube_urls(text, max_urls=10):
    """Read up to 10 unique, validated YouTube URLs, one per line."""
    urls = []
    seen = set()
    for line in str(text or "").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        url = valid_youtube_url(line.strip())
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
            if len(urls) >= max_urls:
                break
    return urls


def parse_progress_status(text):
    """Accepted values for root status.txt, with a safe default."""
    value = str(text).strip().casefold()
    return "Paused" if value == "paused" else "In-Progress"


def find_media(api, repo, screenshot_revisions=None):
    """Read repo artwork, explicit videos, prose and root status.txt."""
    owner, name = repo["owner"]["login"], repo["name"]
    branch = repo.get("default_branch") or "main"
    tree = api.get(f"/repos/{quote(owner)}/{quote(name)}/git/trees/{quote(branch, safe='')}",
                   {"recursive": 1}, optional=True)
    paths = {}
    paths_meta = {}
    if isinstance(tree, dict) and isinstance(tree.get("tree"), list):
        paths_meta = {entry["path"].lower(): entry for entry in tree["tree"]
                      if entry.get("type") == "blob" and isinstance(entry.get("path"), str)}
        paths = {entry["path"].lower(): entry["path"] for entry in tree["tree"]
                 if entry.get("type") == "blob" and isinstance(entry.get("path"), str)}

    # A truncated/unavailable Git tree needs explicit directory listings.
    # GitHub's contents/assets listing is not recursive, so also list
    # assets/screenshots to include screenshots from both locations.
    if not paths or (isinstance(tree, dict) and tree.get("truncated")):
        for folder in ("assets", "assets/screenshots"):
            listing = api.get(f"/repos/{quote(owner)}/{quote(name)}/contents/{folder}",
                              {"ref": branch}, optional=True)
            if isinstance(listing, list):
                for entry in listing:
                    if entry.get("type") == "file" and isinstance(entry.get("path"), str):
                        paths[entry["path"].lower()] = entry["path"]
                        paths_meta[entry["path"].lower()] = entry

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
    # Blob SHAs are identity proofs, not just timestamps. A renamed/removed
    # screenshot is never restored from the thumbnail cache, and replacing
    # bytes at the same URL necessarily changes the cache key.
    if screenshot_revisions is not None:
        for path in candidates[:32]:
            entry = paths_meta.get(path.lower())
            if entry and isinstance(entry.get("sha"), str):
                screenshot_revisions[asset_url(repo, path)] = entry["sha"]
    cover = asset_url(repo, cover_path) if cover_path else (shots[0] if shots else "")
    youtube_urls = []
    description = ""
    progress_status = "In-Progress"
    if "assets/youtube.txt" in paths:
        youtube_urls = parse_youtube_urls(read_repo_text(api, repo, paths["assets/youtube.txt"]))
    if "assets/description.txt" in paths:
        description = read_repo_text(api, repo, paths["assets/description.txt"], max_bytes=8_000)
    if "status.txt" in paths:
        raw_status = read_repo_text(api, repo, paths["status.txt"], max_bytes=128)
    elif not paths or (isinstance(tree, dict) and tree.get("truncated")):
        # A missing/truncated Git tree must not hide a root status.txt.
        raw_status = read_repo_text(api, repo, "status.txt", max_bytes=128)
    else:
        raw_status = ""
    progress_status = parse_progress_status(raw_status)
    if raw_status and raw_status.strip().casefold() not in {"paused", "in-progress"}:
        print(f"WARN: {repo['full_name']} status.txt must be Paused or In-Progress; defaulting to In-Progress", file=sys.stderr)
    return cover, shots, youtube_urls, description, progress_status


def latest_qualifying_timestamp(*values):
    """Latest valid UTC instant, or empty when no relevant event has a date."""
    valid = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                valid.append((parsed.astimezone(timezone.utc), value))
        except ValueError:
            continue
    return max(valid, default=(None, ""))[1]


def release_metadata(api, repo, include_published=False, include_history=False):
    """Latest published release and last change to any retrieved published release.

    Draft releases are ignored. Editing a release counts as a release update;
    unrelated repository pushes and assets outside releases do not.
    """
    owner, name = repo["owner"]["login"], repo["name"]
    releases = api.get(f"/repos/{quote(owner)}/{quote(name)}/releases", {"per_page": 100}, optional=True) or []
    published = [r for r in releases if isinstance(r, dict) and not r.get("draft")]
    if not published:
        result = (False, "", "", "")
        values = (*result, "") if include_published else result
        return (*values, []) if include_history else values
    latest = max(enumerate(published), key=lambda pair:
                 (pair[1].get("published_at") or pair[1].get("created_at") or "", -pair[0]))[1]
    changed_at = latest_qualifying_timestamp(*(
        date for release in published for date in
        (release.get("published_at"), release.get("updated_at"))
    ))
    result = (True, latest.get("html_url", ""), latest.get("tag_name", ""), changed_at)
    # The showcase ranks by the selected release publication date, not by the
    # latest activity date or edits to any other published release. Full builds
    # also request the fifth publication-time field and release history.
    published_at = latest.get("published_at") or latest.get("created_at") or ""
    values = (*result, published_at) if include_published else result
    return (*values, published) if include_history else values


def commit_date(entry):
    """Use the commit date, not GitHub's last repository push timestamp."""
    commit = entry.get("commit") if isinstance(entry, dict) else None
    if not isinstance(commit, dict):
        return ""
    committer = commit.get("committer") or {}
    author = commit.get("author") or {}
    return (latest_qualifying_timestamp(committer.get("date") if isinstance(committer, dict) else "") or
            latest_qualifying_timestamp(author.get("date") if isinstance(author, dict) else ""))


def recent_commit_date(api, repo, path=None):
    """Latest commit affecting one path, or any commit when path is omitted."""
    owner, name = repo["owner"]["login"], repo["name"]
    params = {"per_page": 1}
    if path is not None:
        params = {"path": path, **params}
    try:
        commits = api.get(f"/repos/{quote(owner)}/{quote(name)}/commits",
                          params, optional=True) or []
    except RuntimeError as exc:
        print(f"WARN: commit history unavailable for {repo['full_name']} ({path or 'all'}): {exc}", file=sys.stderr)
        return ""
    return commit_date(commits[0]) if isinstance(commits, list) and commits else ""


def status_change_date(api, repo):
    """Latest commit touching root status.txt, including deletions."""
    return recent_commit_date(api, repo, "status.txt")


def first_commit_date(api, repo):
    """Earliest repository commit, found via GitHub's last commit-history page.

    `created_at` is deliberately not used: creating a repository and making its
    initial commit can occur on different dates. The Link header supplies the
    last page so an old repository requires only two small API requests.
    """
    owner, name = repo["owner"]["login"], repo["name"]
    path = f"/repos/{quote(owner)}/{quote(name)}/commits"
    params = {"per_page": 1}
    try:
        first_page = api.get(path, params, optional=True) or []
        if not isinstance(first_page, list) or not first_page:
            return ""
        link = getattr(api, "pagination_link", None)
        last_url = link(path, params, "last") if callable(link) else ""
        if last_url:
            last_page = api.get(last_url, optional=True) or []
            return commit_date(last_page[0]) if isinstance(last_page, list) and last_page else ""
        # With no pagination, this repository has one commit.
        return commit_date(first_page[0])
    except RuntimeError as exc:
        print(f"WARN: first-commit history unavailable for {repo['full_name']}: {exc}", file=sys.stderr)
        return ""


def tracked_update_date(api, repo, release_changed_at, flags=DEFAULT_UPDATE_FLAGS):
    """Latest selected event; fallback to first commit, then creation date."""
    dates = []
    if flags & UPDATE_RELEASES:
        dates.append(release_changed_at)
    if flags & UPDATE_STATUS:
        dates.append(status_change_date(api, repo))
    if flags & UPDATE_ASSETS:
        dates.append(recent_commit_date(api, repo, "assets"))
    if flags & UPDATE_ANY_COMMIT:
        dates.append(recent_commit_date(api, repo))
    # The first commit is the baseline only when no configured event applies.
    # An empty repository has no commit history, so use its creation time.
    return (latest_qualifying_timestamp(*dates)
            or first_commit_date(api, repo)
            or latest_qualifying_timestamp(repo.get("created_at")))


def release_stage_from_tag(tag):
    """Detect the current release stage from its tag (not the prerelease flag).

    Match complete stage markers, including numeric suffixes such as beta2,
    but do not mistake unrelated words like ``alphabet`` or ``betamax`` for
    release stages. A tag without either marker is an ordinary release.
    """
    match = re.search(r"(?<![a-z])(alpha|beta)(?![a-z])", str(tag or ""), flags=re.IGNORECASE)
    return match.group(1).capitalize() if match else ""


def make_project(api, repo, overrides, igdb=None, igdb_settings=None, links=None, update_flags=DEFAULT_UPDATE_FLAGS, release_event_sink=None):
    full_name = repo["full_name"]
    detected = detect_platforms(repo)
    # A repository cover wins. If only screenshots exist, IGDB should supply
    # the actual box art instead of treating a screenshot as a poster.
    override = {k.lower(): v for k, v in overrides.items()}.get(full_name.lower(), {})
    platforms = configured_platforms(override, detected)
    platform = " / ".join(platforms) or "Other"
    screenshot_revisions = {}
    cover, screenshots, youtube_urls, game_description, progress_status = find_media(api, repo, screenshot_revisions)
    if release_event_sink is None:
        has_release, release_url, release_tag, release_changed_at, release_published_at = release_metadata(api, repo, include_published=True)
        published_releases = []
    else:
        has_release, release_url, release_tag, release_changed_at, release_published_at, published_releases = release_metadata(
            api, repo, include_published=True, include_history=True)
    last_content_update = tracked_update_date(api, repo, release_changed_at, update_flags)
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
    # An actual published GitHub Release takes precedence over root status.txt.
    status = "Released" if has_release else progress_status
    project = {
        "id": full_name.lower(), "repo": full_name,
        "title": display_title(repo, platform),
        "description": repo.get("description") or "No repository description provided.",
        "platform": platform, "platforms": platforms, "status": status,
        "unreleased_status": progress_status,
        "topics": repo.get("topics") or [],
        "owner": repo["owner"]["login"], "stars": repo.get("stargazers_count") or 0,
        "forks": repo.get("forks_count") or 0,
        "updated_at": last_content_update,
        "github_url": repo.get("html_url") or "https://github.com/" + full_name,
        "homepage": repo.get("homepage") or "",
        "issue_url": (repo.get("html_url") or "https://github.com/" + full_name) + "/issues/new/choose" if repo.get("has_issues", True) else "",
        "release_url": release_url,
        "release_tag": release_tag,
        "release_published_at": release_published_at if has_release else "",
        "has_release": has_release,
        "release_stage": release_stage_from_tag(release_tag) if has_release else "",
        "cover_url": cover, "screenshots": screenshots, "_screenshot_revisions": screenshot_revisions,
        "youtube_urls": youtube_urls,
        "igdb_title": (igdb_result or {}).get("name") or "",
        "youtube_match_titles": override.get("youtube_match_titles", []),
        "game_description": chosen_description,
        "description_source_url": chosen_description_source,
        "description_source": description_source,
        "igdb_url": igdb_source,
        "wikipedia_url": external_links["wikipedia_url"],
        "mobygames_url": external_links["mobygames_url"],
        "cover_source": ("repository" if local_cover_exists else ("igdb" if igdb_result and cover == cover_image(igdb_result) else ("screenshot" if cover else "placeholder"))),
    }
    # Do not allow config overrides to falsify release detection or status.txt.
    allowed = {"title", "description", "game_description", "description_source_url",
               "cover_url", "screenshots",
               "homepage"}
    project.update({k: v for k, v in override.items() if k in allowed})
    # An explicit video list replaces the repository youtube.txt entries.
    if "youtube_urls" in override:
        raw_urls = override["youtube_urls"]
        if not isinstance(raw_urls, list) or not all(isinstance(url, str) for url in raw_urls):
            raise ValueError(f"{full_name}: youtube_urls override must be an array of URLs")
        project["youtube_urls"] = parse_youtube_urls("\n".join(raw_urls))
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
    # Collect every published release already returned by the GitHub API,
    # not just the latest tag used by the carousel. No additional API calls.
    if release_event_sink is not None:
        for release in published_releases:
            tag = release.get("tag_name") or ""
            when = release.get("published_at") or release.get("created_at") or ""
            url = release.get("html_url") or ""
            if tag and when and url:
                release_event_sink.append({
                    "repo": full_name, "title": project["title"],
                    "platform": project["platform"],
                    "has_release": True, "release_tag": tag,
                    "release_published_at": when, "release_url": url,
                    "release_stage": release_stage_from_tag(tag),
                })
    return project


def index_youtube(projects, settings, env=None):
    """Link discoverable channel videos and return minimal change-watch metadata."""
    env = os.environ if env is None else env
    channel = (env.get("YOUTUBE_CHANNEL_ID") or settings.get("channel") or "").strip()
    key = (env.get("YOUTUBE_API_KEY") or "").strip()
    if not settings.get("enabled", True) or not channel:
        return {"status": "not_configured", "channel": "", "videos": []}
    validated = parse_channel(channel)
    if not validated:
        print("WARN: Invalid YouTube channel configured", file=sys.stderr)
        return {"status": "error", "channel": "", "videos": []}
    try:
        videos = YouTubeChannel(channel, key, settings.get("max_videos", 1000)).videos()
        associate_videos(projects, videos, settings.get("max_per_game", 5))
        linked = sum(len(p.get("youtube_videos", [])) for p in projects)
        print(f"YouTube: linked {linked} channel videos to {sum(bool(p.get('youtube_videos')) for p in projects)} games.")
        return {"status": "complete", "channel": validated[1], "videos": videos}
    except (RuntimeError, ValueError) as exc:
        print(f"WARN: YouTube channel lookup skipped: {exc}", file=sys.stderr)
        return {"status": "error", "channel": validated[1], "videos": []}


def load_platform_colors(env=None):
    """Palette comes from an Actions JSON variable or private config checkout."""
    env = os.environ if env is None else env
    defaults = ROOT / 'platform-colors.json'
    colors = _json_object(defaults.read_text(encoding='utf-8'), 'platform-colors.json') if defaults.is_file() else {}
    private = private_config_directory(env)
    if private is not None:
        path = private / 'platform-colors.json'
        if path.is_file():
            colors = _json_object(path.read_text(encoding='utf-8'), 'platform-colors.json')
    if env.get('CATALOG_PLATFORM_COLORS_JSON', '').strip():
        colors = _json_object(env['CATALOG_PLATFORM_COLORS_JSON'], 'CATALOG_PLATFORM_COLORS_JSON')
    for platform, pair in colors.items():
        if not isinstance(pair, dict) or not all(
            re.fullmatch(r'#[0-9a-fA-F]{6}', str(pair.get(key, '')))
            for key in ('background', 'text')
        ):
            raise ValueError(f'Invalid platform color for {platform}')
    return colors


def main():
    config = load_config()
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    owner = os.getenv("GITHUB_OWNER", "").strip()
    api = GitHubAPI(token)
    repos = discover_repos(api, config, owner)
    igdb_settings = config.get("igdb", {})
    update_flags = parse_update_flags(config)
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
    feed_releases = []
    for i, repo in enumerate(repos, 1):
        print(f"[{i}/{len(repos)}] Indexing {repo['full_name']}")
        try:
            projects.append(make_project(api, repo, config.get("overrides", {}), igdb, igdb_settings, links, update_flags,
                                         release_event_sink=feed_releases))
        except RuntimeError as exc:
            print(f"WARN: could not enrich {repo['full_name']}: {exc}", file=sys.stderr)
            # Keep the project even if additional metadata failed.
            fallback = GitHubAPI(token)
            fallback.get = lambda *args, **kwargs: []
            projects.append(make_project(fallback, repo, config.get("overrides", {}), igdb, igdb_settings, links, update_flags,
                                         release_event_sink=feed_releases))
    # Only current GitHub blob identities may reuse persistent thumbnails.
    cache_root = cache_directory()
    generate_thumbnails(projects, ROOT / "site" / "assets" / "thumbnails", config.get("thumbnails", {}),
                        cache_dir=cache_root)
    # Match available channel uploads to game titles.
    youtube_state = index_youtube(projects, config.get("youtube", {}))
    # A fresh liveness check is mandatory before publishing links. This also
    # validates youtube.txt and manually overridden links, not just channel matches.
    media_status = remove_unavailable_videos(projects, os.getenv("YOUTUBE_API_KEY", ""))
    print(f"YouTube liveness: {media_status['checked']} checked, "
          f"{media_status['removed']} unavailable, {media_status['unverified']} unverified (omitted)")
    # Publish a compact watch snapshot for the five-minute scheduled checker.
    # Only publicly observable source metadata and video titles are stored here.
    from scripts.watch import build_snapshot
    snapshot = build_snapshot(repos, projects, youtube_state)
    snapshot_file = ROOT / "site" / "data" / "watch-state.json"
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    snapshot_file.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Remove the internal matcher fields even if channel discovery is disabled.
    for project in projects:
        project.pop("igdb_title", None)
        project.pop("youtube_match_titles", None)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "site": load_site_settings(config),
        "platform_colors": load_platform_colors(),
        "projects": projects,
        "owners": config["discovery"].get("owners") or ([owner] if owner else [])
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    feed_count = build_rss_feed(projects, payload["site"], ROOT / "site" / "feed.xml",
                                os.environ, update_flags, release_history=feed_releases)
    print(f"RSS feed: {feed_count} update entries")
    save_history(cache_root, ROOT / "site" / "feed.xml", OUTPUT)
    has_about = render_about_page()
    print(f"Wrote {len(projects)} projects to {OUTPUT.relative_to(ROOT)}")
    print(f"About page: {'rendered from private about.md' if has_about else 'blank (no private content)'}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
