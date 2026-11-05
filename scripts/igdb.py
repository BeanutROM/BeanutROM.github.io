"""Optional IGDB enrichment for the static game catalog.

Queries IGDB only during the Python build. Twitch app credentials and OAuth
access tokens never enter the static JSON, browser, or generated site.
"""
from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
GAME_URL = "https://api.igdb.com/v4/games"
IMAGE_URL = "https://images.igdb.com/igdb/image/upload/t_cover_big_2x/{}.jpg"

# Compare the platform reported by the repository with the platforms on the
# IGDB game record. When a record explicitly lists different consoles, do not
# silently assign that record's artwork to the wrong game.
PLATFORM_NAMES = {
    # MAME is the catalog's display name; IGDB calls this platform Arcade.
    "MAME": ("arcade",),
    "PS1": ("playstation", "ps1", "psx"),
    "PS2": ("playstation 2", "ps2"),
    "PS3": ("playstation 3", "ps3"),
    "PS4": ("playstation 4", "ps4"),
    "PS5": ("playstation 5", "ps5"),
    "PSP": ("playstation portable", "psp"),
    "Vita": ("playstation vita", "psvita", "vita"),
    "Xbox": ("xbox", "xbox original"),
    "Xbox 360": ("xbox 360", "x360"),
    "Xbox One": ("xbox one", "xone"),
    "Xbox Series": ("xbox series x s", "xbox series", "series x", "series s"),
    "Wii": ("wii",),
    "Wii U": ("wii u", "wiiu"),
    "GameCube": ("nintendo gamecube", "gamecube", "gcn", "ngc"),
    "N64": ("nintendo 64", "n64"),
    "SNES": ("super nintendo entertainment system", "super famicom", "snes"),
    "NES": ("nintendo entertainment system", "famicom", "nes"),
    "Switch": ("nintendo switch", "switch"),
    "3DS": ("nintendo 3ds", "3ds"),
    "NDS": ("nintendo ds", "nintendo dsi", "ds", "nds"),
    "GBA": ("game boy advance", "gba"),
    "GBC": ("game boy color", "gbc"),
    "GB": ("game boy", "gb"),
    "Dreamcast": ("dreamcast",),
    "Saturn": ("sega saturn", "saturn"),
    "Genesis": ("sega mega drive genesis", "sega mega drive", "sega genesis", "mega drive", "genesis"),
    "Sega CD": ("sega cd", "mega cd"),
    "32X": ("sega 32x", "32x"),
    "Master System": ("sega master system mark iii", "sega master system", "master system"),
    "Game Gear": ("game gear",),
    "PC Engine": ("turbografx 16 pc engine", "turbografx 16", "pc engine", "supergrafx"),
    "PC Engine CD": ("turbografx cd", "pc engine cd", "pc engine super cd rom"),
    "PC-FX": ("pc fx",),
    "PC-98": ("pc 9801", "pc 98", "nec pc 9801"),
    "PC-88": ("pc 8801", "pc 88"),
    "Neo Geo": ("neo geo aes", "neo geo mvs", "neo geo"),
    "Neo Geo CD": ("neo geo cd",),
    "Neo Geo Pocket": ("neo geo pocket",),
    "Neo Geo Pocket Color": ("neo geo pocket color",),
    "WonderSwan": ("wonderswan",),
    "WonderSwan Color": ("wonderswan color",),
    "3DO": ("3do interactive multiplayer", "3do"),
    "Jaguar": ("atari jaguar", "jaguar"),
    "Virtual Boy": ("virtual boy",),
    "N-Gage": ("n gage", "ngage"),
    "PC": ("pc microsoft windows", "pc windows", "windows", "pc"),
    "DOS": ("dos", "pc dos"),
    "MSX": ("msx",),
    "MSX2": ("msx2", "msx 2"),
    "X68000": ("sharp x68000", "x68000"),
    "FM Towns": ("fm towns", "fm towns marty"),
    "Amiga": ("amiga",),
    "C64": ("commodore c64 128 max", "commodore 64", "c64"),
    "Atari 2600": ("atari 2600",),
    "Atari 5200": ("atari 5200",),
    "Atari 7800": ("atari 7800",),
    "Lynx": ("atari lynx",),
    "CD-i": ("philips cd i", "cd i"),
    "Odyssey 2": ("odyssey 2", "philips videopac g7000"),
    "ColecoVision": ("colecovision",),
    "Intellivision": ("intellivision",),
    "Vectrex": ("vectrex",),
    "SG-1000": ("sg 1000",),
}


def normalize(text):
    """Use conservative normalization, not arbitrary substring matching."""
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").casefold().replace("&", " and ")))


def platform_matches(platform, igdb_platforms):
    """Accept any confirmed platform for a multi-platform project."""
    platforms = platform if isinstance(platform, (list, tuple)) else [platform]
    platforms = [name for name in platforms if name and name != "Other"]
    if not platforms or not igdb_platforms:
        return None
    allowed = {normalize(alias) for name in platforms
               for alias in PLATFORM_NAMES.get(name, (name,))}
    for item in igdb_platforms:
        if not isinstance(item, dict):
            continue
        if any(normalize(item.get(key)) in allowed for key in ("name", "abbreviation") if item.get(key)):
            return True
    return False


def title_tokens(text):
    """Compare game names without requiring the optional 'and' or '&'."""
    return tuple(part for part in normalize(text).split() if part != "and")


def title_match_quality(lookup, candidate, minimum_similarity=0.94):
    """Rank exact, equivalent-punctuation, subtitle, then near-exact matches.

    Do not accept arbitrary word containment: it can confuse sequels, remakes,
    spin-offs, and unrelated games with a shared word.
    """
    lookup_raw = normalize(lookup)
    candidate_raw = normalize(candidate)
    if not lookup_raw or not candidate_raw:
        return 0.0
    if lookup_raw == candidate_raw:
        return 1.0
    words = title_tokens(lookup)
    other = title_tokens(candidate)
    if words and words == other:
        return 0.99  # Venus Braves = Venus & Braves = Venus and Braves

    # A shortened title may omit a genuine subtitle, indicated explicitly by
    # punctuation in the IGDB name. A bare word prefix is NOT sufficient.
    # Examples: "Hikari no Shima" -> "Hikari no Shima: Seven Lithographs..."
    # But "Sample Quest" should not match "Sample Quest II".
    if len(words) >= 2 and len("".join(words)) >= 8:
        base = re.split(r"\s*(?:[:：]|[（(\[])|\s+[-–—]\s+", candidate, maxsplit=1)[0]
        if len(base) < len(candidate) and title_tokens(base) == words:
            return 0.90

    # A regional prefix may appear before the shorter repository title:
    # "Pride of the Dragon Peace" -> "Waga Ryuu o Miyo: Pride of the Dragon Peace".
    # Require a clear colon and a substantial multiword segment; never accept
    # arbitrary suffix containment or a sequel-number variant.
    if len(words) >= 3 and len("".join(words)) >= 12:
        segments = re.split(r"\s*[:：]\s*", candidate)
        if len(segments) > 1 and title_tokens(segments[-1]) == words:
            return 0.89

    # Preserve a limited amount of the old near-exact spelling tolerance,
    # but do not use it to justify long-prefix partial results.
    if len(words) == len(other) and words and words[0] == other[0]:
        similarity = SequenceMatcher(None, " ".join(words), " ".join(other)).ratio()
        if similarity >= minimum_similarity:
            return 0.75 + (similarity - minimum_similarity) / 4
    return 0.0


def choose_game(results, title, platform, minimum_similarity=0.94):
    """Find a compatible IGDB game, declining ambiguous partial matches."""
    if not title_tokens(title):
        return None
    ranked = []
    for item in results:
        if not isinstance(item, dict) or not isinstance(item.get("cover"), dict):
            continue
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", str(item["cover"].get("image_id", ""))):
            continue
        match = platform_matches(platform, item.get("platforms"))
        if match is False:
            continue
        names = [item.get("name")]
        names += [entry.get("name") for entry in (item.get("alternative_names") or [])
                  if isinstance(entry, dict)]
        quality = max((title_match_quality(title, name, minimum_similarity)
                       for name in names), default=0.0)
        if not quality:
            continue
        # Choose the strongest name match first, then a verified platform.
        ranked.append(((quality, 1 if match is True else 0), item))
    if not ranked:
        return None
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    # Two equally strong records are not a safe automatic cover match.
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


def fallback_queries(title):
    """A few narrower searches for titles IGDB does not tokenize identically."""
    words = title_tokens(title)
    if len(words) < 2:
        return []
    options = []
    if len(words) == 2 and "&" not in title:
        options.append(f"{words[0]} & {words[1]}")
    # A shorter search retrieves titles that add a subtitle or a connector.
    # The strict client-side ranking still decides whether any hit is safe.
    anchor = next((word for word in words if len(word) >= 4 and
                   word not in {"the", "this", "that", "from", "with"}), "")
    if anchor and sum(len(word) for word in words) >= 9:
        options.append(anchor)
    return [q for q in dict.fromkeys(options) if normalize(q) != normalize(title)]


def cover_image(game):
    image_id = (game.get("cover") or {}).get("image_id", "")
    return IMAGE_URL.format(image_id) if re.fullmatch(r"[a-zA-Z0-9_-]+", str(image_id)) else ""


def game_page(game):
    slug = str(game.get("slug") or "")
    return "https://www.igdb.com/games/" + slug if re.fullmatch(r"[a-z0-9-]+", slug) else ""


class IGDBClient:
    def __init__(self, client_id, client_secret, min_interval=0.28):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = ""
        self.cache = {}
        self.min_interval = min_interval
        self.last_request = 0.0

    def _authorize(self):
        if self.token:
            return
        form = urlencode({"client_id": self.client_id,
                          "client_secret": self.client_secret,
                          "grant_type": "client_credentials"}).encode("utf-8")
        request = Request(TOKEN_URL, data=form, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "game-catalog-builder"}, method="POST")
        # Do not display response bodies or request secrets in errors.
        try:
            with urlopen(request, timeout=20) as response:
                data = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"Twitch OAuth returned HTTP {exc.code}") from None
        except (URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"Twitch OAuth connection failed ({type(exc).__name__})") from None
        token = data.get("access_token", "")
        if not token:
            raise RuntimeError("Twitch OAuth returned no access token")
        self.token = token

    def _query(self, body):
        self._authorize()
        if body in self.cache:
            return self.cache[body]
        now = time.monotonic()
        if self.last_request:
            time.sleep(max(0.0, self.min_interval - (now - self.last_request)))
        request = Request(GAME_URL, data=body.encode("utf-8"), headers={
            "Client-ID": self.client_id,
            "Authorization": "Bearer " + self.token,
            "Content-Type": "text/plain",
            "Accept": "application/json",
            "User-Agent": "game-catalog-builder"}, method="POST")
        for attempt in range(3):
            self.last_request = time.monotonic()
            try:
                with urlopen(request, timeout=20) as response:
                    entries = json.load(response)
                if not isinstance(entries, list):
                    raise RuntimeError("IGDB returned an unexpected response")
                self.cache[body] = entries
                return entries
            except HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"IGDB returned HTTP {exc.code}") from None
            except (URLError, OSError, ValueError) as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"IGDB connection failed ({type(exc).__name__})") from None
        return []

    def get_game(self, title, platform, game_id=None):
        fields = "fields id,name,slug,cover.image_id,platforms.name,platforms.abbreviation,alternative_names.name,summary,websites.url; "
        if game_id is not None:
            # An explicit IGDB ID is authoritative. Do not fuzzy-match it.
            try:
                numeric_id = int(game_id)
            except (TypeError, ValueError):
                return None
            if numeric_id <= 0:
                return None
            matches = self._query(fields + f"where id = {numeric_id}; limit 1;")
            return next((g for g in matches if isinstance(g, dict) and g.get("id") == numeric_id), None)
        title = str(title or "").strip()
        if not title:
            return None
        for query in [title, *fallback_queries(title)]:
            # Always escape Apicalypse literal contents, including controls.
            safe_title = query[:150].replace("\\", "\\\\").replace('"', '\\"')
            safe_title = re.sub(r"[\x00-\x1f\x7f]", " ", safe_title)
            matches = self._query(fields + f'search "{safe_title}"; limit 60;')
            selected = choose_game(matches, title, platform)
            if selected:
                return selected
        return None
