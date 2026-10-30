# Game Catalog

A static GitHub Pages catalog for public game repositories. The site has a single branded header and opens to a searchable **Games** grid. Selecting a game expands a details panel below its entire grid row, with screenshots, optional YouTube videos, project details, and release links.

Built with HTML, CSS, JavaScript, Python 3, and GitHub Actions. No database, npm installation, or browser-side GitHub API calls are required.

## GitHub Pages setup

1. Create a **public** repository for the site. For a user or organization page, name it `<owner>.github.io`; for a project page, use any repository name.
2. Copy the project files into the repository, **including `.github/`**, and push to `main`.
3. Edit `config.json` to choose which GitHub accounts and repositories to index.
4. Under **Settings → Pages → Build and deployment**, select **GitHub Actions** as the source.
5. Run **Actions → Update catalog and deploy Pages**. The workflow also runs when `main` is updated and on a roughly eight-hour schedule.

The workflow fetches public repository information, optionally enriches covers and descriptions through IGDB and verifies external game reference links, generates `site/data/projects.json`, then deploys the `site/` directory. The generated JSON is build output and normally does not need manual editing. GitHub Actions uses its temporary `GITHUB_TOKEN`. API credentials are only read during the build and are never published with the website.

### Deployment history cleanup

The workflow runs three jobs in order: **build → cleanup → publish**. After the build and tests succeed, cleanup removes existing deployment **records** for the `github-pages` environment using `strumwolf/delete-deployment-environment` with `onlyRemoveDeployments: true`. Publishing then creates a new deployment record. The environment itself, Pages configuration, and Actions run history are not deleted.

Cleanup requires the workflow's `GITHUB_TOKEN` to have `deployments: write` permission, granted only to the cleanup job. If cleanup fails, the publish job does not run. Removing the record of the current live deployment before its replacement is published can temporarily affect the displayed deployment status, so prefer to run the workflow when a brief deployment transition is acceptable. No additional secret is required under normal repository settings.

**Preview data:** The package includes fictional sample entries and illustrations for testing the layout. A successful catalog build replaces them with discovered repositories. These samples are not automatically published projects.

## What the catalog looks for

Each indexed repository can supply the following information:

| Information | Source or fallback |
| --- | --- |
| Game title | Cleaned repository name, or a configured override |
| Platform | Repository name, description, then GitHub topics, or a configured override |
| Game description | Configured override, `assets/description.txt`, verified Wikipedia introduction, IGDB summary, or repository description |
| Cover artwork | Repository cover, IGDB (if configured), first repository screenshot, or placeholder |
| Screenshots | Supported images in `assets/` or recognized legacy screenshot directories |
| Videos | `assets/youtube.txt`, plus matching public uploads from an optional YouTube channel |
| Development status | GitHub Releases and, if unreleased, `assets/status.txt` |
| Version | Tag of the most recently published GitHub Release |
| Stars | Actual GitHub `stargazers_count` at the most recent refresh |
| External references | Verified MobyGames and Wikipedia game pages, when found |

The title and platform are inferred from repository metadata even if there are **no assets**. Names with separators, platform labels, and common translation labels are handled heuristically. This does not verify official game names or unusual capitalization. Use `overrides` for exceptions. If the platform cannot be identified, it is displayed as **Other**.

If the name does not identify a platform, the indexer checks the repository description before topics. Multiple consoles in one source are retained: for example, `Example-Game-English-Patch` with description `An English patch for PCFX and PSX` is displayed as **PC-FX / PS1** and appears under either platform filter. A repository with a recognized platform in its name uses that first. Manual `overrides` can provide a single `"platform"` value or a `"platforms"` array for exceptions.

Common platform labels include `PS3`, `Xbox360`/`Xbox 360`, `Wii`, `PS2`, `GameCube`/`GCN`, and `Xbox`, plus earlier home consoles and handhelds. Separators and common abbreviations are recognized; ambiguous names can still be corrected with a configuration override.

Arcade boards are grouped under **MAME** for display and filtering, including aliases such as `ST-V`, `Sega Titan Video`, `CPS-2`, `NAOMI`, `Atomiswave`, and `Neo Geo MVS`. IGDB matches these projects against its **Arcade** platform. Generic terms can be ambiguous; use `overrides` when an arcade term is part of a game's title rather than its hardware label.

### Platform badge colors

The separate root `platform-colors.json` file contains a table with a `background` and `text` hex color for each supported platform, plus `Other` as the fallback. You can update colors without replacing your existing `config.json` or losing metadata overrides. These colors are exported into the generated catalog during the build and applied to badges on game cards and expanded details. The platform dropdown uses the normal control styling. For example:

```json
"platform_colors": {
  "MAME": {"background": "#7536a0", "text": "#ffffff"},
  "PS1":  {"background": "#3c4c88", "text": "#ffffff"},
  "Other": {"background": "#3b484e", "text": "#ffffff"}
}
```

These are illustrative entries from the full table, not a replacement for the existing palette file. Use six-digit hex values (`#RRGGBB`). Editing the table requires only a new catalog build. Multi-platform games display one badge per platform, each with its own colors.

For official titles with unusual spelling that cannot be inferred from the repository name, use a `title` override. For example, `JailBreaker` is deliberately retained as one word when inferred from a matching repository name.

Game cards use an **8.5:11 portrait ratio** to suit cover artwork. The grid displays four cards per row on wide screens, reducing to three, two, or one at smaller widths. Images retain their original proportions, and selecting a card opens the full game details below its row.

The star icon only displays the GitHub star count. Clicking it does **not** star a repository.

## Optional game repository assets

Files are read from each game's **own public repository**, not from the Pages site's `assets/` directory. An example layout:

```text
example-owner/example-game-ps2/
├── assets/
│   ├── cover.png                 # Optional card artwork
│   ├── youtube.txt               # Optional YouTube URL
│   ├── description.txt           # Optional extended description
│   ├── status.txt                # Paused or In-Progress, for unreleased games
│   ├── screenshot-01.png         # Gallery image
│   ├── screenshot-02.webp
│   └── screenshots/
│       └── screenshot-03.jpg
├── README.md
└── ...
```

All these files are optional. The indexer searches recursively under `assets/` when the repository tree is available. Screenshots are ordered naturally, so `2.png` comes before `10.png`. Up to 32 screenshots are indexed per game. The cover is excluded from the screenshot list when other images are available.

Supported screenshot extensions are `.png`, `.jpg`, `.jpeg`, and `.webp`. The scanner also recognizes common existing locations such as `screenshots/`, `docs/screenshots/`, `docs/cover.*`, and root-level `cover.*` files. For cover selection, `assets/cover.*` takes priority, followed by common legacy cover locations, then IGDB (if configured), then the first screenshot. IGDB covers are not added to the repository screenshot gallery.

#### Generated gallery thumbnails

By default, the catalog build downloads each public repository screenshot temporarily and uses the **ImageMagick command-line tool** to generate a small, compressed **WebP** thumbnail (320px maximum width/height). The generated files are published under `site/assets/thumbnails/` with GitHub Pages. **Pillow/PIL is not used or required.**

Only the thumbnail list uses these local files. Opening a screenshot in the large media viewer, or using **View original resolution**, still retrieves the original image directly from its game repository. Official cover artwork and YouTube thumbnails are unchanged. If an image cannot be downloaded or converted, that thumbnail falls back to the original image URL without stopping the build.

To adjust the thumbnail settings, edit `config.json`:

```json
"thumbnails": {
  "enabled": true,
  "width": 320,
  "quality": 76,
  "max_source_bytes": 16777216
}
```

The build job installs ImageMagick explicitly using `apt-get`, so no Python imaging dependencies are required. Local builds can install ImageMagick through their package manager. The converter is optional locally; if unavailable, the catalog still builds with the original image URLs. Each scheduled build fetches its source screenshots again, so the initial build can take longer and use more bandwidth than before. No full-resolution screenshots are stored in the deployed Pages site.

### YouTube video

`assets/youtube.txt` should contain a **single HTTPS YouTube URL**, for example:

```text
https://www.youtube.com/watch?v=VIDEO_ID
```

Supported link forms include `youtube.com/watch?v=...`, `youtu.be/...`, `youtube.com/shorts/...`, `youtube.com/live/...`, and `youtube.com/embed/...`.

The explicit video appears first in the thumbnail list. Additional channel-matched videos can follow it when channel discovery is enabled. Selecting a thumbnail loads a privacy-enhanced YouTube embed in the media viewer **above the details panel**. The embed is not loaded until it is selected. YouTube may collect data after playback is activated.

### Screenshots and expanded details

Selecting a game opens an inline panel beneath its grid row, pushing subsequent rows down rather than covering them. The panel includes a vertical thumbnail list alongside game information.

Selecting an image displays the original full-resolution screenshot above the panel. **View original resolution** opens the source image hosted by the game repository. Selecting another thumbnail switches media. The viewer also has **Previous** and **Next** arrow buttons on either side; the keyboard **Left** and **Right** arrow keys perform the same navigation. Both directions wrap between the first and last item, including YouTube videos and screenshots in a single sequence. Keyboard shortcuts are ignored when typing into form fields. If the YouTube iframe has keyboard focus, its own player controls receive the arrow keys; click outside the video to use the catalog shortcuts. **Close** hides the viewer without collapsing the game details.

The details header shows the platform, a game title linked to the repository, and the latest published release tag linked to that release. If no release exists, it shows **No release** rather than a made-up version.

### No `assets/` folder?

The game can still be indexed. Missing assets only affect the associated media or metadata:

| Missing item | Behavior |
| --- | --- |
| Entire `assets/` folder, or an empty folder | The game still appears |
| All covers and screenshots | IGDB cover if configured and a confident match exists; otherwise a text-based poster. Expanded media panel remains empty without repository media |
| `youtube.txt` | No explicit video; matching channel videos can still appear |
| `description.txt` | Verified Wikipedia introduction when available; otherwise IGDB, repository description, or a placeholder |
| `status.txt` | In-Progress when unreleased; Released if a published release exists |
| Any published GitHub Release | **No release** is shown instead of a version |
| Recognizable platform information | Platform displays as **Other** |

Repository metadata and GitHub Releases are fetched independently of the assets directory.

## Status and releases

A game is marked **Released** if at least one published GitHub Release exists. A published prerelease counts; a draft release does not. Release state takes precedence over `assets/status.txt`.

For games without a published release, create `assets/status.txt` containing one of these values:

```text
Paused
```

or

```text
In-Progress
```

The file may contain surrounding whitespace and is read without regard to capitalization. The status filter offers **All**, **Released**, **Paused**, and **In-Progress**.

| Published GitHub Release? | `assets/status.txt` | Displayed status |
| --- | --- | --- |
| Yes | Any value or missing | **Released** |
| No | `Paused` | **Paused** |
| No | `In-Progress` | **In-Progress** |
| No | Missing, empty, or invalid | **In-Progress** |

Unknown status values produce a build warning and default to **In-Progress** when unreleased. Archived repositories use the same rules. `config.json` overrides cannot force a release state or status; use a GitHub Release or the status file in the game repository.

The file is read from the game's **default branch** during each catalog build. The example file in `examples/game-repository/assets/status.txt` can be copied into a game repository.

## Descriptions and source attribution

For expanded game details, `assets/description.txt` provides optional UTF-8 text. If absent, the builder prefers the introduction from a **verified Wikipedia video-game article**, followed by an IGDB summary and then the GitHub repository description. A configured `game_description` takes precedence over every automatic source. Wikipedia excerpts come from the public MediaWiki API and are attributed to Wikipedia contributors under CC BY-SA 4.0 with a source and license link. Articles without a confident title/platform match, generic lists, unavailable summaries, and API failures fall back to IGDB. No MobyGames API subscription or webpage scraping is used.

Example `config.json` override:

```json
{
  "overrides": {
    "example-owner/example-game-ps2": {
      "title": "Example Game: Complete Edition",
      "platform": "PS2",
      "game_description": "An original or appropriately licensed description of the game.",
      "description_source_url": "https://example.com/game-information"
    }
  }
}
```

The source URL is displayed as a **Description source** link. The override above is a **fragment** illustrating the `overrides` object, not a complete replacement for the site's configuration.

IGDB lookups use its official API, and Wikipedia and Wikidata links use public APIs. No MobyGames API requests or webpage scraping are performed. When neither Wikipedia nor IGDB has a suitable game description, the repository description is used. You can supply original or appropriately licensed text using `assets/description.txt` or an override.

## Optional IGDB artwork and game descriptions

IGDB can supply **official game cover art** when a repository does not contain its own cover. It can also supply a game summary when no local or verified Wikipedia description is available. No `assets/` directory is required for IGDB lookup. This is an optional build-time integration; the site works without it.

### Create Twitch application credentials

1. Open the [Twitch Developer Console](https://dev.twitch.tv/console/apps) and register an application with **Confidential** client type. A valid localhost redirect URL can be used; IGDB does not use it.
2. Copy its **Client ID** and generate a **Client Secret**.
3. In the **GitHub repository that hosts the website**, open **Settings → Secrets and variables → Actions → New repository secret** and add both entries:

   | Secret name | Value |
   | --- | --- |
   | `IGDB_CLIENT_ID` | Twitch application Client ID |
   | `IGDB_CLIENT_SECRET` | Twitch application Client Secret |

4. Run **Actions → Update catalog and deploy Pages → Run workflow** (or push a commit to `main`). The next build will query IGDB for eligible games.

**Keep the client secret private.** Never add credentials to `config.json`, commit them, paste them into public issues, or embed them into site JavaScript. The workflow sends them to Twitch to request a short-lived app token and uses the token to call IGDB. The public site receives only image URLs, summary text, and links. IGDB cover images are served by IGDB's public image CDN, not copied into the Pages repository.

### Artwork priority and matching

1. An explicit `cover_url` configured for a game takes priority, followed by a dedicated cover image inside its repository.
2. Otherwise, the builder looks for the game on IGDB by inferred title and checks the detected platform when IGDB supplies platform information. It only accepts high-confidence matches.
3. If no suitable IGDB cover is found, the first repository screenshot is used, followed by a text-based placeholder.

Matching recognizes equivalent connectors (for example, `Sample Quest` and `Sample & Quest`), shortened names followed by a subtitle (for example, `Island Quest` and `Island Quest: The Lost Maps`), and shortened names following a regional prefix (for example, `Island Quest` and `Original Regional Title: Island Quest`). If the full-title search returns no suitable results, the builder tries a limited shorter search. It still checks console compatibility, prefers exact titles, and rejects ambiguous matches rather than choosing arbitrary artwork.

Some regional or translated game names may still need a manual override. Screenshot galleries continue to use repository assets; video galleries may also use an optional YouTube channel.

For example, specify an IGDB ID or an alternative search name in `config.json`:

```json
{
  "overrides": {
    "example-owner/example-game-ps2": {
      "igdb_id": 12345
    },
    "example-owner/alternate-title-ps1": {
      "igdb_query": "Original Game Title"
    }
  }
}
```

The ID is illustrative; replace it with the actual IGDB game ID. A fixed `igdb_id` bypasses fuzzy matching and should be verified before use. These are fragments of the `overrides` object, not replacements for the complete configuration. A custom `cover_url` overrides the IGDB image when necessary.

IGDB lookup is controlled by this optional `config.json` section:

```json
"igdb": {
  "enabled": true,
  "use_summaries": true
}
```

Set `use_summaries` to `false` to disable IGDB summaries (without disabling Wikipedia descriptions), or `enabled` to `false` to disable all IGDB lookups. Without both secrets, the indexer skips IGDB automatically. No token rotation or browser API is needed. The builder limits requests to IGDB's documented rate limit and retains repeated query results within each build.

## Optional YouTube channel videos

To discover additional videos from a public channel at build time, add the following to the **GitHub Pages repository** under **Settings → Secrets and variables → Actions**:

| Type | Name | Value |
| --- | --- | --- |
| **Variable or Secret** | `YOUTUBE_CHANNEL_ID` | A channel ID beginning with `UC`, an `@handle`, or the corresponding YouTube channel URL |
| **Secret** (recommended) | `YOUTUBE_API_KEY` | A Google Cloud API key authorized for **YouTube Data API v3** |

The API key is **not** a Twitch/IGDB credential. In Google Cloud, enable **YouTube Data API v3** for your project, then create an API key under **APIs & Services → Credentials**. You do not need YouTube account OAuth for public uploads. Keep the key in GitHub Actions secrets, not in site JavaScript or the public repository. Restrict the key to the YouTube Data API where possible.

With an API key, the indexer resolves the channel's public **uploads playlist** and pages through up to `max_videos` videos. This avoids repeatedly calling the more expensive per-game search API. With only a **UC... channel ID** and no key, it can use YouTube's public RSS feed, which only supplies recent uploads, not the complete back catalog. `@handles` require an API key. If the channel is inaccessible, the catalog continues building without channel videos.

The build compares video titles with inferred game names, including missing ampersands, added subtitles, regional title prefixes, and common gameplay/translation suffixes. Ambiguous matches are omitted. Up to `max_per_game` matching channel videos are placed in each game's media thumbnails, **after** any explicit `assets/youtube.txt` video and before screenshots. Video titles are preserved for accessible thumbnail labels; selecting a video loads the YouTube embed above the details panel. You can optionally add alternate titles for difficult cases:

```json
{
  "overrides": {
    "example-owner/example-game-ps2": {
      "youtube_match_titles": ["Example Game", "Alternate Regional Title"]
    }
  }
}
```

The optional `config.json` settings are:

```json
"youtube": {
  "enabled": true,
  "max_videos": 1000,
  "max_per_game": 5
}
```

`YOUTUBE_CHANNEL_ID` takes priority over the optional `youtube.channel` config value. Only public videos accessible through the API/feed can be indexed. The browser performs no YouTube Data API calls, and the key is never added to `projects.json`. The site updates on the existing GitHub Actions schedule or when a new build is triggered.

### YouTube indexing diagnostics

Each build reports the YouTube channel configuration and indexing results under **Actions → Update catalog and deploy Pages → build → Fetch public repositories and build catalog**. The workflow also adds a **YouTube channel indexing** summary to that run.

To inspect every video title, open the completed run's **Artifacts** section and download **`youtube-diagnostics`**. It contains `youtube-diagnostics.json` with:

- `status`: `complete`, `missing_channel`, `disabled`, or `error`.
- `channel`, `method` (`api` or `rss`), and whether an API key was configured.
- `videos_retrieved`, `videos_matched`, and overall `outcomes` counts.
- Each video's title and result: `matched`, `no_title_match`, `ambiguous_match`, `per_game_limit`, `duplicate_explicit_video`, or `duplicate_channel_video`.
- Each game's matching titles and matched channel videos. `matching_limited: true` identifies titles too short for the automatic matcher (for example, short generic one-word names). Distinctive titles of eight or more letters, including joined or separated spellings, can match automatically.

The diagnostic JSON is an Actions artifact, **not** part of the public Pages site, and contains no API credentials. It is retained for 14 days. A video can be indexed without being matched: compare its actual title with the project's `match_titles`, then add a `youtube_match_titles` override when needed. Explicit `assets/youtube.txt` links still work independently of channel indexing.

If the report says `missing_channel`, set `YOUTUBE_CHANNEL_ID` under Actions Variables **or** Secrets. If `error` shows HTTP 403, inspect the reported API reason and check that YouTube Data API v3 is enabled and your key is allowed to use it. If `videos_retrieved` is nonzero but `videos_matched` is zero, inspect the video-title matches rather than the API credentials.

## MobyGames and Wikipedia links

The **expanded game details** panel can show links to the corresponding MobyGames and Wikipedia game pages. When a verified Wikipedia game article supplies a usable introduction, the builder prefers that text to IGDB's summary and includes a Wikipedia source and CC BY-SA 4.0 license link. These links are resolved **during the catalog build**, so the published page makes no live metadata API requests.

The builder first checks websites associated with a confidently matched IGDB game. It **rejects Wikipedia list/index pages and any Wikipedia article URL that does not contain a recognizable portion of the game's title**. This applies even to links suggested by IGDB and to manual URL overrides. If no suitable link remains, it searches English Wikipedia, allowing punctuation variants and subtitles, while rejecting unrelated or ambiguous entries. If that article has a Wikidata item with a MobyGames game identifier, the corresponding MobyGames page is linked automatically.

MobyGames links are retrieved only from links associated with a matched IGDB record or identifiers provided by Wikidata. **No MobyGames subscription or API key is required.** The builder does not scrape MobyGames webpages or import their descriptions. Games without a verified link simply omit the MobyGames button.

Links are included only for confident matches. Missing or ambiguous results are omitted. For example, a generic Wikipedia **List of downloadable PlayStation games** page is not accepted as a reference for an individual game, even if IGDB associates that page with it. The builder does **not** fabricate a URL from the repository name, and not every game has a Wikipedia article. The existing IGDB matching and manual `igdb_query` / `igdb_id` overrides help resolve regional or abbreviated names.

For exceptional cases, link directly to the verified article in `config.json`:

```json
{
  "overrides": {
    "example-owner/example-game-ps2": {
      "wikipedia_url": "https://en.wikipedia.org/wiki/Example_(video_game)",
      "mobygames_url": "https://www.mobygames.com/game/12345/"
    }
  }
}
```

These addresses are illustrative: replace them with **real** article/game URLs. Overrides reject unrelated domains and search-result pages. To disable all external link lookups, set `"external_links": {"enabled": false}` in `config.json`.

## Website colors and theme

The default dark and light themes use the purple, blue-green, and evergreen gradient palette from the site's artwork. Site-wide colors and gradients are defined near the top of `site/styles.css` under `:root` (dark) and `:root[data-theme="light"]` (light). Adjust those variables to change the page background, surfaces, controls, and highlights; the theme switcher is retained.

Platform labels use the **separate** `platform-colors.json` table and are not recolored by the website theme. The logo and favicon remain static PNGs in `site/assets/`.

## Site name and filters

The header uses `site/assets/beanut-logo.png` as its image logo with the tagline displayed to the right. The image alternative text, footer name, and browser title come from `site.name` in `config.json`. The tagline can be edited in `site/index.html`. The repository owner is controlled separately by `discovery.owners` and `site.github_url`. The favicon is `site/assets/favicon.png`, a 256 × 256 PNG. Replace either PNG to update the artwork without changing the indexer.

For example, set the name without changing the repository account or existing game overrides:

```json
"site": {
  "name": "Beanut Translations",
  "github_url": "https://github.com/example-account"
}
```

**Platform**, **Status**, and **Sort by** use square-cornered, page-rendered menus rather than browser-native popups. They match the width, borders, and colors of the surrounding controls and support mouse/touch, Arrow Up/Down, Home/End, Enter, Escape, and outside-click dismissal.

## Discovery and configuration

Edit the existing `config.json` file. It contains site text and links in `site`, discovery rules in `discovery`, and optional per-repository corrections in `overrides`.

The following is a **generic example** of the discovery section, not the current configuration:

```json
{
  "discovery": {
    "owners": ["example-owner"],
    "include_all_owner_repos": true,
    "include_repositories": [],
    "exclude_repositories": ["example-owner/example-owner.github.io"],
    "include_forks": false,
    "search_queries": []
  }
}
```

- **`owners`**: GitHub users or organizations whose repositories may be indexed.
- **`include_all_owner_repos`**: include all qualifying public owner repositories. Set to `false` to rely on configured topic/description matching and explicit inclusions.
- **`include_topics_any` / `include_description_matches`**: topic tags and text phrases used when filtering discovered repositories.
- **`include_repositories`**: individual repositories to include explicitly, in `owner/name` form.
- **`exclude_repositories`**: repositories to omit, such as the Pages site itself or unrelated utilities.
- **`include_forks`**: whether forked repositories are eligible.
- **`search_queries`**: optional GitHub-wide searches outside the configured owners.
- **`search_results_per_query` / `max_projects`**: limits for discovery and output size.

For example, adding a query such as `"topic:fan-translation ps2"` to `search_queries` searches for matching public repositories. It is optional and disabled when the list is empty.

Use `overrides` when a repository's title, platform, or description requires correction. Metadata comes from public GitHub repositories; changes are reflected after the next catalog build.

## Local development

Preview the included sample data:

```bash
python -m http.server 8080 -d site
```

Then open `http://localhost:8080`.

To fetch real repositories and rebuild the catalog first:

```bash
python -m scripts.build
python -m http.server 8080 -d site
```

You can optionally set `GITHUB_TOKEN` in your environment to obtain higher GitHub API limits, or set `IGDB_CLIENT_ID` and `IGDB_CLIENT_SECRET` to use local IGDB enrichment. **Never commit tokens or secrets.** For example, on Windows PowerShell:

```powershell
$env:GITHUB_TOKEN = "YOUR_TOKEN"
python -m scripts.build
python -m http.server 8080 -d site
```

Run the automated checks:

```bash
python -m unittest discover -s tests -v
```

## Implementation notes and limitations

- Catalog metadata is generated at build time using GitHub's REST API, IGDB, and Wikimedia APIs. Visitor browsers load static JSON and public media, not authenticated API data.
- Only public repositories and publicly accessible assets are indexed. `assets/` content must be committed to each game's default branch.
- The scanner requests the recursive Git tree and can fall back to a direct `assets/` listing if a tree is truncated. Deeply nested files may be missed for extremely large repositories with truncated trees.
- Git LFS objects, private repositories, and files attached only to GitHub Releases are not automatically treated as repository `assets/` files.
- Full-resolution screenshots use public repository URLs; the build creates small local WebP gallery thumbnails in Pages. IGDB cover images remain on IGDB's CDN; video thumbnails and playback depend on YouTube. The full-resolution media is not copied into the Pages repository.
- The GitHub star count is a snapshot from the most recent index build and is not a starring action.
- Scheduled workflow runs may be delayed. Use the manual **Actions** workflow to refresh on demand.
- GitHub API rate limits and transient failures can cause builds to fail; the build should not be mistaken for a live, continuously updated index.

## Project files

```text
config.json                         Site settings, discovery rules, metadata overrides
scripts/build.py                    GitHub indexer and catalog generator
scripts/igdb.py                     Optional IGDB API integration
scripts/youtube.py                  Optional YouTube channel indexing
scripts/game_links.py               Wikipedia excerpts, Wikipedia/Wikidata and IGDB external links
site/index.html                     Games page layout
site/styles.css                     Theme and responsive styling
site/app.js                         Search, filters, expanded rows, media viewer
site/data/projects.json             Sample data replaced by the indexer
site/demo-images/*.svg              Illustrative preview artwork
site/assets/thumbnails/*.webp       Generated during build, not committed
scripts/thumbnails.py              Download/conversion with ImageMagick (no Pillow)
.github/workflows/pages.yml         Scheduled refresh and GitHub Pages deployment
tests/test_build.py                 GitHub indexer tests
tests/test_igdb.py                  IGDB matching and API tests
tests/test_igdb_integration.py      IGDB indexer integration tests
tests/test_youtube.py               YouTube channel matching and API tests
tests/test_game_links.py            External game reference link tests
examples/game-repository/assets/status.txt   Example development status file
```


### Navigation

On desktop screens (wider than 820px), the site header and single-row search, platform, status, and sort controls remain visible while scrolling. On tablet and mobile widths, they scroll normally. The header displays the total number of indexed games, regardless of filtering.

### Background styling

The header, search/filter area, and footer use the page-wide purple-to-green background rather than separate section gradients. On desktop, sticky navigation paints the same fixed page gradient to keep scrolling game covers from showing through its controls. On mobile, these sections are transparent and scroll normally. Search and filter controls have transparent interiors, while open dropdown menus use a solid background for readability.
