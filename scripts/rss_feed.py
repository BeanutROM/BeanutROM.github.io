"""Generate a stable RSS 2.0 update feed for the static game catalog.

Feed items reflect published GitHub releases and actual project-status
transitions, not ordinary commits, screenshots, or YouTube matches.

Because Pages deployments replace the entire site, the builder reads the
previously deployed feed and projects.json before publishing a new version.
That preserves historical items without repository write-back or secrets.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from scripts.cache_state import cache_directory
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ATOM = "http://www.w3.org/2005/Atom"
ET.register_namespace("atom", ATOM)
MAX_ITEMS = 100
MAX_FETCH_BYTES = 4 * 1024 * 1024


def parse_date(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        try:
            result = parsedate_to_datetime(str(value))
        except (TypeError, ValueError, IndexError):
            return None
    if result.tzinfo is None:
        return None
    return result.astimezone(timezone.utc)


def absolute_http_url(value):
    try:
        url = urlsplit(str(value or ""))
        if url.scheme not in ("https", "http") or not url.netloc or url.username or url.password:
            return ""
        return urlunsplit((url.scheme, url.netloc, url.path, url.query, ""))
    except ValueError:
        return ""


def feed_guid(kind, repo, key):
    identity = f"{kind}\0{str(repo).casefold()}\0{key}"
    return "urn:game-catalog:" + kind + ":" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def site_address(env):
    """Canonical Pages URL in Actions, optionally supplied for custom domains."""
    from scripts.watch import site_url
    override = str(env.get("CATALOG_SITE_URL", "")).strip()
    repo = str(env.get("GITHUB_REPOSITORY", "")).strip()
    if not override and not repo:
        return ""  # Offline builds do not fetch deployed history.
    return site_url(repo, override)


def fetch_published(base_url, filename):
    """Return deployed bytes, or None for a page not yet published.

    Fail closed for network/server errors: silently resetting a history feed
    on a temporary outage would permanently lose older items.
    """
    # A unique query string avoids a stale Pages/CDN response during rapid
    # consecutive deployments. The queried resource remains the same file.
    marker = int(datetime.now(timezone.utc).timestamp() * 1000000)
    url = base_url.rstrip("/") + "/" + filename + f"?snapshot={marker}"
    request = Request(url, headers={"User-Agent": "game-catalog-rss-builder/1.0",
                                    "Cache-Control": "no-cache"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = response.read(MAX_FETCH_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (404, 410):
            return None
        raise RuntimeError(f"Published {filename} returned HTTP {exc.code}") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise RuntimeError(f"Could not retrieve previous {filename}: {exc}") from exc
    if len(payload) > MAX_FETCH_BYTES:
        raise RuntimeError(f"Published {filename} exceeds the {MAX_FETCH_BYTES} byte safety limit")
    return payload


def read_previous_feed(content):
    """Validate and read our RSS items; do not accept arbitrary XML elements."""
    if content is None:
        return {}
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise RuntimeError(f"Published feed.xml is invalid XML: {exc}") from exc
    if root.tag != "rss" or root.attrib.get("version") != "2.0":
        raise RuntimeError("Published feed.xml is not RSS 2.0")
    channel = root.find("channel")
    if channel is None:
        raise RuntimeError("Published feed.xml has no channel")
    result = {}
    for node in channel.findall("item"):
        guid = (node.findtext("guid") or "").strip()
        title = (node.findtext("title") or "").strip()
        link = absolute_http_url(node.findtext("link"))
        stamp = parse_date(node.findtext("pubDate"))
        if not guid.startswith("urn:game-catalog:") or not title or not link or not stamp:
            continue
        result[guid] = {"guid": guid, "title": title, "link": link,
                        "description": node.findtext("description") or "",
                        "category": node.findtext("category") or "Update", "date": stamp}
    return result


def read_previous_projects(content):
    if content is None:
        return {}
    try:
        payload = json.loads(content)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"Published projects.json is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("projects"), list):
        raise RuntimeError("Published projects.json has an invalid project list")
    return {str(p["repo"]).casefold(): p for p in payload["projects"]
            if isinstance(p, dict) and p.get("repo")}


def release_items(projects):
    for p in projects:
        if not p.get("has_release") or not p.get("release_tag"):
            continue
        repo = p.get("repo") or p.get("id")
        date = parse_date(p.get("release_published_at"))
        link = absolute_http_url(p.get("release_url"))
        if not repo or not date or not link:
            continue
        title = str(p.get("title") or repo)
        tag = str(p["release_tag"])
        stage = str(p.get("release_stage") or "").lower()
        category = "Beta release" if stage == "beta" else "Alpha release" if stage == "alpha" else "Full release"
        yield {
            "guid": feed_guid("release", repo, tag),
            "title": f"{title}: {tag} ({category})",
            "link": link,
            "description": f"{title} published {tag}. Platform: {p.get('platform') or 'Unknown'}. Download and release notes are available on GitHub.",
            "category": category,
            "date": date,
        }


def status_items(projects, previous):
    """Announce transitions only, not every build or the initial inventory."""
    for p in projects:
        repo = str(p.get("repo") or "").casefold()
        prior = previous.get(repo)
        if not prior or p.get("has_release"):
            continue  # A newly published release already generates its own item.
        before = str(prior.get("status") or "")
        after = str(p.get("status") or "")
        if not before or not after or before == after:
            continue
        date = parse_date(p.get("updated_at")) or datetime.now(timezone.utc)
        # Never give an item a timestamp older than the previous state record.
        old_date = parse_date(prior.get("updated_at"))
        if old_date is not None and date <= old_date:
            date = datetime.now(timezone.utc)
        title = str(p.get("title") or repo)
        link = absolute_http_url(p.get("github_url"))
        if not link:
            continue
        yield {
            "guid": feed_guid("status", repo, f"{before}/{after}/{date.isoformat()}"),
            "title": f"{title}: {after}",
            "link": link,
            "description": f"{title} changed project status from {before} to {after}.",
            "category": "Status change", "date": date,
        }


def write_rss(projects, site, output_file, base_url="", previous_feed=None,
              previous_projects=None, update_flags=3, max_items=MAX_ITEMS,
              release_history=None):
    """Combine selected events with previous items and serialize RSS 2.0."""
    events = read_previous_feed(previous_feed)
    old_projects = read_previous_projects(previous_projects)
    # Defaults follow updates.flags: release events = bit 1, status = bit 2.
    if update_flags & 1:
        for item in release_items(projects if release_history is None else release_history):
            events.setdefault(item["guid"], item)
    if update_flags & 2:
        for item in status_items(projects, old_projects):
            events.setdefault(item["guid"], item)
    items = sorted(events.values(), key=lambda e: (e["date"], e["guid"]), reverse=True)[:max_items]

    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    title = str(site.get("name") or "Game Catalog")
    link = absolute_http_url(base_url) or absolute_http_url(site.get("github_url")) or "https://github.com/"
    for tag, value in (("title", f"{title} updates"), ("link", link),
                       ("description", f"Published releases and project status updates from {title}."),
                       ("language", "en"), ("generator", "Game Catalog"), ("ttl", "60")):
        ET.SubElement(channel, tag).text = value
    if base_url:
        ET.SubElement(channel, f"{{{ATOM}}}link", {
            "href": base_url.rstrip("/") + "/feed.xml",
            "rel": "self", "type": "application/rss+xml",
        })
    if items:
        ET.SubElement(channel, "lastBuildDate").text = format_datetime(items[0]["date"], usegmt=True)
    for event in items:
        node = ET.SubElement(channel, "item")
        for tag, value in (("title", event["title"]), ("link", event["link"]),
                           ("description", event["description"]),
                           ("category", event["category"]),
                           ("pubDate", format_datetime(event["date"], usegmt=True))):
            ET.SubElement(node, tag).text = value
        ET.SubElement(node, "guid", {"isPermaLink": "false"}).text = event["guid"]
    ET.indent(rss, space="  ")
    path = Path(output_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(rss).write(path, encoding="utf-8", xml_declaration=True)
    return len(items)


def build_rss_feed(projects, site, output_file, env=None, update_flags=3, release_history=None):
    """Build from live data and the prior published site, if available."""
    env = {} if env is None else env
    base = site_address(env)
    previous_feed = previous_projects = None
    root = cache_directory(env)
    # Prefer the currently deployed site because its state can be newer than a
    # cache push that failed after deployment. Durable cache is only a fallback.
    try:
        if base:
            previous_feed = fetch_published(base, "feed.xml")
            previous_projects = fetch_published(base, "data/projects.json")
    except RuntimeError:
        if not root or not (root / 'rss' / 'feed.xml').is_file() or not (root / 'rss' / 'projects.json').is_file():
            raise
        print('WARN: Published RSS history unavailable; restoring durable cache fallback')
    if root:
        for filename, current in (('feed.xml', previous_feed), ('projects.json', previous_projects)):
            if current is None:
                path = root / 'rss' / filename
                if path.is_file():
                    candidate = path.read_bytes()
                    if len(candidate) <= MAX_FETCH_BYTES:
                        if filename == 'feed.xml':
                            previous_feed = candidate
                        else:
                            previous_projects = candidate
    return write_rss(projects, site, output_file, base, previous_feed,
                     previous_projects, update_flags, release_history=release_history)
