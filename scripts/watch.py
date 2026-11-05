"""Lightweight 5-minute check: rebuild only for relevant GitHub/YouTube changes.

The reference snapshot is written during catalog builds and published
alongside projects.json. Scheduled checks use that published snapshot directly,
without downloading the optional thumbnail/RSS cache repository.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from scripts.build import GitHubAPI, discover_repos, release_metadata, load_config, private_config_fingerprint, ROOT
from scripts.youtube import YouTubeChannel, associate_videos, parse_channel
from scripts.media_validation import check_videos, video_id

SNAPSHOT = ROOT / "site" / "data" / "watch-state.json"
CONFIG = ROOT / "config.json"
SCHEMA = 1
RECENT_VIDEO_LIMIT = 50
MAX_RELEASE_LOOKUPS_PER_POLL = 60  # Keeps GITHUB_TOKEN usage under 1,000 calls/hour.


def repo_stamp(repo, release_tag="", release_url=""):
    """Only public properties relevant to the rendered catalog."""
    return {
        "pushed_at": repo.get("pushed_at") or "",
        "updated_at": repo.get("updated_at") or "",
        "description": repo.get("description") or "",
        "topics": sorted(str(t) for t in (repo.get("topics") or [])),
        "default_branch": repo.get("default_branch") or "",
        "release_tag": release_tag or "",
        "release_url": release_url or "",
    }


def build_snapshot(repos, projects, youtube_state=None):
    """Store only metadata required to detect meaningful future changes."""
    youtube_state = youtube_state or {}
    project_map = {p["repo"].casefold(): p for p in projects}
    project_titles = []
    for p in projects:
        project_titles.append({
            "repo": p["repo"], "title": p["title"],
            "match_titles": list(dict.fromkeys(n for n in
                [p["title"], p.get("igdb_title", ""), *(p.get("youtube_match_titles") or [])] if n)),
            "platforms": p.get("platforms", []),
            "youtube_urls": p.get("youtube_urls", []),
        })
    matched = {
        (video_id(entry.get("url", ""))): p["repo"]
        for p in projects for entry in (p.get("youtube_videos") or [])
        if video_id(entry.get("url", ""))
    }
    recent = [{"id": v.get("id", ""), "title": v.get("title", ""),
               "game": matched[v["id"]]}
              for v in (youtube_state.get("videos") or [])[:RECENT_VIDEO_LIMIT]
              if v.get("id") in matched]
    return {
        "schema_version": SCHEMA,
        "private_config_hash": private_config_fingerprint(),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repositories": {
            repo["full_name"].casefold(): repo_stamp(
                repo,
                project_map.get(repo["full_name"].casefold(), {}).get("release_tag", ""),
                project_map.get(repo["full_name"].casefold(), {}).get("release_url", ""),
            ) for repo in repos
        },
        "youtube": {
            "status": youtube_state.get("status", "not_configured"),
            "channel": youtube_state.get("channel") or "",
            "recent": recent,
            "projects": project_titles,
            "published_ids": sorted({video
                for p in projects
                for url in ((p.get("youtube_urls") or [])
                            + [v.get("url", "") for v in p.get("youtube_videos", [])])
                if (video := video_id(url))}),
        },
    }


def site_url(repository, override=""):
    """Return the static Pages URL, supporting username and project sites."""
    if override:
        if not re.fullmatch(r"https://[a-zA-Z0-9.-]+(?:/[a-zA-Z0-9._/-]*)?", override.rstrip("/")):
            raise ValueError("CATALOG_SITE_URL must be an HTTPS site URL")
        return override.rstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("GITHUB_REPOSITORY is missing or invalid")
    owner, repo = repository.split("/", 1)
    root = f"https://{owner.lower()}.github.io"
    return root if repo.casefold() == f"{owner}.github.io".casefold() else f"{root}/{quote(repo, safe='')}"


def fetch_snapshot(url):
    request = Request(url.rstrip("/") + "/data/watch-state.json?" + urlencode({"t": int(datetime.now(timezone.utc).timestamp())}),
                      headers={"User-Agent": "game-catalog-change-watcher/1.0", "Cache-Control": "no-cache"})
    try:
        with urlopen(request, timeout=20) as response:
            data = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise RuntimeError(f"Published catalog snapshot returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot retrieve published catalog snapshot: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA:
        raise RuntimeError("Published catalog snapshot is invalid; use a manual build to restore it")
    return data


def repo_changes(baseline, current):
    old = baseline.get("repositories") or {}
    if old == current:
        return []
    messages = []
    for repo in sorted(current.keys() - old.keys()):
        messages.append(f"New tracked repository: {repo}")
    for repo in sorted(old.keys() - current.keys()):
        messages.append(f"Removed/untracked repository: {repo}")
    for repo in sorted(current.keys() & old.keys()):
        if current[repo] != old[repo]:
            changes = [field for field in current[repo] if current[repo].get(field) != old[repo].get(field)]
            messages.append(f"Repository updated: {repo} ({', '.join(changes)})")
    return messages


def video_changes(baseline, videos, max_per_game=5):
    """Only new or edited videos that match a project trigger a rebuild."""
    prior = (baseline.get("youtube") or {}).get("recent") or []
    previous = {v["id"]: v for v in prior if v.get("id")}
    projects = []
    for entry in (baseline.get("youtube") or {}).get("projects") or []:
        names = list(entry.get("match_titles") or [])
        projects.append({
            "repo": entry.get("repo", ""), "title": entry.get("title", ""),
            "youtube_match_titles": names,
            "platforms": entry.get("platforms", []),
            "youtube_urls": entry.get("youtube_urls", []),
        })
    associate_videos(projects, videos, max_per_game=max_per_game)
    messages = []
    for project in projects:
        for entry in project.get("youtube_videos") or []:
            vid = video_id(entry["url"])
            old = previous.get(vid)
            if not old or old.get("game") != project["repo"] or old.get("title") != entry["title"]:
                messages.append(f"New/updated matching YouTube video: {entry['title']} ({project['repo']})")
    return messages


def missing_video_changes(baseline, api_key='', slot=None, max_keyless=20, max_keyed=100):
    """Rebuild if a previously published video is confirmed unavailable.

    Spread liveness checks across scheduled five-minute runs. Keyed API
    requests are batched 50 per HTTP call, with a small per-poll limit to
    conserve daily API quota. Keyless oEmbed checks have an even lower limit.
    """
    history = baseline.get('youtube') or {}
    ids = history.get('published_ids')
    if not isinstance(ids, list):
        return []
    ids = sorted(set(value for value in ids if isinstance(value, str) and len(value) == 11))
    if not ids:
        return []
    limit = max_keyed if api_key else max_keyless
    if len(ids) > limit:
        from math import ceil
        segments = ceil(len(ids) / limit)
        if slot is None:
            slot = int(datetime.now(timezone.utc).timestamp() // 300)
        offset = (slot % segments) * limit
        ids = ids[offset:offset + limit]
    available = check_videos(ids, api_key)
    return [f'Previously published YouTube video unavailable: {video}'
            for video in ids if available.get(video) is False]


def check_changes(config, baseline, api, env):
    owners = env.get("GITHUB_OWNER", "")
    repos = discover_repos(api, config, owners)
    current = {}
    old_repos = baseline.get("repositories") or {}
    # GitHub's standard GITHUB_TOKEN has a 1,000-request hourly budget.
    # For large collections, rotate the release checks across polls. All
    # repository metadata is still checked on every five-minute run.
    shards = max(1, (len(repos) + MAX_RELEASE_LOOKUPS_PER_POLL - 1) // MAX_RELEASE_LOOKUPS_PER_POLL)
    slot = int(datetime.now(timezone.utc).timestamp() // 300) % shards
    for i, repo in enumerate(repos):
        key = repo["full_name"].casefold()
        old = old_repos.get(key) or {}
        if i % shards == slot:
            published, url, tag = release_metadata(api, repo)[:3]
            release_tag, release_url = (tag if published else ""), (url if published else "")
        else:
            release_tag, release_url = old.get("release_tag", ""), old.get("release_url", "")
        current[key] = repo_stamp(repo, release_tag, release_url)
    changes = repo_changes(baseline, current)
    youtube_settings = config.get("youtube") or {}
    channel = (env.get("YOUTUBE_CHANNEL_ID") or youtube_settings.get("channel") or "").strip()
    if youtube_settings.get("enabled", True) and channel:
        key = (env.get("YOUTUBE_API_KEY") or "").strip()
        parsed = parse_channel(channel)
        previously = (baseline.get("youtube") or {}).get("channel", "")
        if not parsed:
            print("WARN: Invalid YouTube channel configured", file=sys.stderr)
        elif parsed[1] != previously:
            changes.append("YouTube channel configuration changed")
        else:
            try:
                videos = YouTubeChannel(channel, key, RECENT_VIDEO_LIMIT).videos()
                changes.extend(video_changes(baseline, videos, youtube_settings.get("max_per_game", 5)))
                print(f"Watch: scanned {len(videos)} recent channel videos")
            except (RuntimeError, ValueError) as exc:
                print(f"WARN: YouTube check failed; GitHub checks still ran: {exc}", file=sys.stderr)
    elif (baseline.get("youtube") or {}).get("channel") and not channel:
        changes.append("YouTube channel configuration removed")
    changes.extend(missing_video_changes(baseline, (env.get('YOUTUBE_API_KEY') or '').strip()))
    return changes


def write_step_output(deploy, reasons):
    outcome = "true" if deploy else "false"
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"deploy={outcome}\n")
    print(f"Watch result: deploy={outcome}")
    for reason in reasons:
        print("  - " + reason)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("### Catalog change detection\n\n")
            handle.write(f"- Rebuild: **{'Yes' if deploy else 'No'}**\n")
            for reason in reasons:
                handle.write(f"- {reason.replace('|', '/')}\n")


def main():
    event = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    if event != "schedule":
        write_step_output(True, [f"Immediate build requested by {event}"])
        return
    config = load_config()
    url = site_url(os.getenv("GITHUB_REPOSITORY", ""), os.getenv("CATALOG_SITE_URL", ""))
    baseline = fetch_snapshot(url)
    if baseline is None:
        write_step_output(True, ["No published watch snapshot yet; building initial catalog"])
        return
    if baseline.get("private_config_hash", "") != private_config_fingerprint():
        write_step_output(True, ["Private configuration changed"])
        return
    token = os.getenv("GITHUB_TOKEN")
    changes = check_changes(config, baseline, GitHubAPI(token), os.environ)
    write_step_output(bool(changes), changes or ["No tracked repository updates or matching new YouTube videos"])


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"ERROR: Watch failed without removing any existing deployment: {exc}", file=sys.stderr)
        sys.exit(1)
