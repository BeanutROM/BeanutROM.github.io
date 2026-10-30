"""Optional, build-time links to actual Wikipedia and MobyGames game pages.

Sources: a matched IGDB record's linked websites, and Wikipedia's
public API plus Wikidata MobyGames identifiers. No MobyGames API or
webpage scraping. No browser-side requests or guessed slugs.
"""
from __future__ import annotations

import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, unquote
from urllib.request import Request, urlopen

from scripts.igdb import fallback_queries, title_match_quality, title_tokens

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"
# Give Wikimedia an identifiable application URL rather than a default Python agent.
USER_AGENT = "GameCatalog/1.0 (https://github.com/BeanutROM/BeanutROM.github.io; metadata linking)"


def verified_url(url, service):
    """Never publish a search page, untrusted redirect, or an invented game URL."""
    try:
        parts = urlsplit(str(url or ""))
        if parts.scheme != "https" or parts.username or parts.password or parts.port:
            return ""
        host = (parts.hostname or "").lower()
        if service == "wikipedia":
            return str(url) if host == "en.wikipedia.org" and parts.path.startswith("/wiki/") and len(parts.path) > 6 else ""
        if service == "mobygames":
            return str(url) if host in {"www.mobygames.com", "mobygames.com"} and re.fullmatch(r"/game/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)?/?", parts.path) else ""
    except (ValueError, TypeError):
        pass
    return ""



# Page URLs must identify the actual game, not a related console or a list
# of games. We compare meaningful words from the original/official title
# against the decoded Wikipedia article slug, not snippets or link labels.
WIKI_NON_GAME_PREFIXES = (
    "list of ", "lists of ", "category:", "index of ", "outline of ",
    "comparison of ", "timeline of ", "bibliography of ",
)
TITLE_STOPWORDS = frozenset({
    "a", "an", "and", "at", "by", "for", "from", "in", "no", "of",
    "on", "or", "the", "to", "with", "game", "video", "version",
})


def verified_wikipedia_game_url(url, *names):
    """Only accept an English Wikipedia article whose slug names the game.

    Generic list/index pages are never game references. A multiword title
    must contribute at least two meaningful words to the page path. A
    distinctive one-word title can match by itself. Subtitles and regional
    prefixes are allowed, but an unrelated PlayStation-games page is not.
    """
    approved = verified_url(url, "wikipedia")
    if not approved:
        return ""
    page = page_name(approved)
    lowered = page.casefold().strip()
    if any(lowered.startswith(prefix) for prefix in WIKI_NON_GAME_PREFIXES):
        return ""
    article_words = set(title_tokens(page))
    for name in names:
        words = {word for word in title_tokens(str(name or ""))
                 if word not in TITLE_STOPWORDS and len(word) >= 3}
        if not words:
            continue
        overlap = words.intersection(article_words)
        contains_name = ((len(words) >= 2 and len(overlap) >= 2) or
                         (len(words) == 1 and len(next(iter(words))) >= 6 and bool(overlap)))
        # Matching words alone are not enough to justify a sequel or a
        # similarly named spin-off. Require a recognized whole-title relation.
        if contains_name and match_wikipedia_title(name, page) >= .89:
            return approved
    return ""


def normalized_moby_url(url):
    """Upgrade trusted MobyGames page links to HTTPS, rejecting other hosts."""
    try:
        parts = urlsplit(str(url or ""))
        if parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.port:
            return ""
        if (parts.hostname or "").lower() not in {"mobygames.com", "www.mobygames.com"}:
            return ""
        return verified_url(parts._replace(scheme="https").geturl(), "mobygames")
    except (ValueError, TypeError):
        return ""

def urls_from_igdb(game, *names):
    """IGDB websites use URL/domain instead of deprecated website category codes."""
    links = {"wikipedia_url": "", "mobygames_url": ""}
    for entry in (game or {}).get("websites") or []:
        if not isinstance(entry, dict):
            continue
        for name, service in (("wikipedia_url", "wikipedia"), ("mobygames_url", "mobygames")):
            if not links[name]:
                links[name] = (verified_wikipedia_game_url(entry.get("url"), *names)
                               if service == "wikipedia" and names else
                               normalized_moby_url(entry.get("url")) if service == "mobygames" else
                               verified_url(entry.get("url"), service))
    return links


def page_name(url):
    parts = urlsplit(url)
    if parts.hostname != "en.wikipedia.org" or not parts.path.startswith("/wiki/"):
        return ""
    return unquote(parts.path[6:]).replace("_", " ")


def match_wikipedia_title(query, title):
    """Require the game's name, not a sequel or unrelated name containing it."""
    cleaned = re.sub(r"\s*\((?:\d{4}\s+)?(?:video game|computer game)\)\s*$", "", str(title), flags=re.I)
    return title_match_quality(query, cleaned)


def pick_wikipedia(results, title):
    """Only select a uniquely confident game article, never a search page."""
    ranked = []
    for item in results:
        candidate = str(item.get("title", ""))
        quality = match_wikipedia_title(title, candidate)
        if quality < .90 or not item.get("pageid"):
            continue
        # Search snippets may be truncated, so do not use them to rule out games.
        ranked.append((quality, item))
    ranked.sort(key=lambda e: e[0], reverse=True)
    if not ranked or (len(ranked) > 1 and ranked[0][0] == ranked[1][0]):
        return None
    return ranked[0][1]


def wikidata_moby_url(entity):
    claims = entity.get("claims") or {}
    # Current numeric IDs are preferred. P1933 is an older slug scheme.
    for statement in claims.get("P11688", []):
        value = (statement.get("mainsnak") or {}).get("datavalue", {}).get("value", "")
        if re.fullmatch(r"[1-9]\d*", str(value)):
            return "https://www.mobygames.com/game/" + str(value) + "/"
    for statement in claims.get("P1933", []):
        value = (statement.get("mainsnak") or {}).get("datavalue", {}).get("value", "")
        if re.fullmatch(r"[a-z0-9_-]+", str(value)):
            return "https://www.mobygames.com/game/" + str(value)
    return ""


class GameLinksClient:
    def __init__(self, min_wiki_interval=.35):
        self.min_wiki_interval = min_wiki_interval
        self.last_request = {}
        self.cache = {}

    def _get(self, url, service):
        if url in self.cache:
            return self.cache[url]
        pause = self.min_wiki_interval
        last = self.last_request.get(service, 0)
        if last:
            time.sleep(max(0, pause - (time.monotonic() - last)))
        self.last_request[service] = time.monotonic()
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                data = json.load(response)
            self.cache[url] = data
            return data
        except (HTTPError, URLError, OSError, ValueError) as error:
            # Avoid printing full request URLs in build logs.
            raise RuntimeError(f"{service} lookup failed ({type(error).__name__})") from None

    def _wiki_page(self, title, platforms=()):
        """Retrieve Wikipedia search results; skip unverified and ambiguous titles."""
        for query in [title, *fallback_queries(title)]:
            if len(title_tokens(query)) == 0:
                continue
            url = WIKIPEDIA_API + "?" + urlencode({"action": "query", "list": "search",
                "srsearch": query, "srnamespace": 0, "srlimit": 15, "format": "json"})
            data = self._get(url, "wiki")
            result = pick_wikipedia(data.get("query", {}).get("search", []), title)
            if not result:
                continue
            # Confirm the page is about a video game, not merely a matching title.
            info_url = WIKIPEDIA_API + "?" + urlencode({"action": "query", "prop": "extracts|pageprops",
                "exintro": 1, "explaintext": 1, "exchars": 700, "pageids": result["pageid"], "format": "json"})
            info = self._get(info_url, "wiki").get("query", {}).get("pages", {})
            record = info.get(str(result["pageid"])) or {}
            extract = record.get("extract") or ""
            # A genuine video-game article almost always introduces itself as one.
            if not re.search(r"\b(?:video|computer|role.playing|adventure|puzzle|arcade|simulation) game\b", extract, re.I):
                continue
            # When Wikipedia explicitly names a console in the introduction,
            # check it against the project's detected platform(s).
            from scripts.build import platforms_in_text
            detected = platforms_in_text(extract)
            expected = [p for p in platforms if p != "Other"]
            if detected and expected and not set(detected).intersection(expected):
                continue
            page = record.get("title") or result["title"]
            wiki_url = "https://en.wikipedia.org/wiki/" + quote(page.replace(" ", "_"), safe="()_:-")
            if not verified_wikipedia_game_url(wiki_url, title):
                continue
            return (wiki_url, (record.get("pageprops") or {}).get("wikibase_item", ""))
        return "", ""

    def wikipedia_description(self, wiki_url, titles, platforms=()):
        """Return a verified video-game article introduction, or no description.

        This uses the public MediaWiki API, never webpage scraping. The returned
        excerpt is shortened by Wikipedia's TextExtracts API; callers must link
        to the article and show the CC BY-SA attribution when displaying it.
        """
        names = tuple(name for name in titles if isinstance(name, str) and name.strip())
        if not names or not verified_wikipedia_game_url(wiki_url, *names):
            return ""
        url = WIKIPEDIA_API + "?" + urlencode({
            "action": "query", "prop": "extracts|pageprops", "exintro": 1,
            "explaintext": 1, "exchars": 1100,
            "titles": page_name(wiki_url), "redirects": 1, "format": "json",
        })
        data = self._get(url, "wiki")
        for record in (data.get("query") or {}).get("pages", {}).values():
            if (not isinstance(record, dict) or "missing" in record or
                    "invalid" in record or
                    "disambiguation" in (record.get("pageprops") or {})):
                continue
            canonical_title = str(record.get("title") or "")
            canonical_url = ("https://en.wikipedia.org/wiki/" +
                             quote(canonical_title.replace(" ", "_"), safe="()_:-"))
            # A redirect must still resolve to an article about the game.
            if not verified_wikipedia_game_url(canonical_url, *names):
                continue
            intro = re.sub(r"\s+", " ", str(record.get("extract") or "")).strip()
            if not intro or not re.search(
                r"\b(?:video|computer|console|arcade|action|adventure|role.playing|"
                r"platform|puzzle|simulation|strategy|fighting|racing|shooting|"
                r"rhythm|horror|sports|tactical|survival|action.adventure) game\b",
                intro, re.I,
            ):
                continue
            from scripts.build import platforms_in_text
            detected = platforms_in_text(intro)
            expected = [platform for platform in platforms if platform != "Other"]
            if detected and expected and not set(detected).intersection(expected):
                continue
            return intro
        return ""

    def _wiki_entity(self, wiki_url):
        if not verified_url(wiki_url, "wikipedia"):
            return ""
        page = page_name(wiki_url)
        url = WIKIPEDIA_API + "?" + urlencode({"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
                                             "titles": page, "redirects": 1, "format": "json"})
        data = self._get(url, "wiki")
        pages = (data.get("query") or {}).get("pages", {})
        for item in pages.values():
            qid = (item.get("pageprops") or {}).get("wikibase_item", "")
            if re.fullmatch(r"Q[1-9]\d*", qid):
                return qid
        return ""

    def _moby_from_wikidata(self, qid):
        if not re.fullmatch(r"Q[1-9]\d*", str(qid)):
            return ""
        data = self._get(WIKIDATA_ENTITY.format(qid), "wiki")
        entity = (data.get("entities") or {}).get(qid, {})
        return wikidata_moby_url(entity)

    def find(self, title, platforms, igdb_game=None):
        official_name = str((igdb_game or {}).get("name") or title)
        alternative_names = [str(item.get("name") or "") for item in
                             ((igdb_game or {}).get("alternative_names") or [])
                             if isinstance(item, dict)]
        titles = tuple(dict.fromkeys([title, official_name, *alternative_names]))
        links = urls_from_igdb(igdb_game, *titles)
        # An IGDB match helps resolve regional names, while preserving strict
        # title validation when no matched IGDB game is available.
        wiki = links["wikipedia_url"]
        qid = ""
        if not wiki:
            for query in dict.fromkeys([official_name, title]):
                try:
                    wiki, qid = self._wiki_page(query, platforms)
                    if wiki:
                        break
                except RuntimeError:
                    continue
        # Validate every discovered Wikipedia URL, including those from IGDB.
        wiki = verified_wikipedia_game_url(wiki, *titles)
        if wiki and not qid:
            try:
                qid = self._wiki_entity(wiki)
            except RuntimeError:
                pass
        moby = links["mobygames_url"]
        if not moby and qid:
            try:
                moby = self._moby_from_wikidata(qid)
            except RuntimeError:
                pass
        result = {"wikipedia_url": wiki, "mobygames_url": moby}
        return result
