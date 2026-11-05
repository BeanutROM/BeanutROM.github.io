# Game Catalog

Game Catalog is a static GitHub Pages website that indexes public game repositories, their releases, screenshots, and videos. A GitHub Actions workflow checks for changes, builds the catalog, and deploys the site. Branding and discovery rules can be supplied from a separate private repository.

The website includes searchable game cards, platform and status filters, a recent-releases carousel, expanded media galleries, an About page, and an RSS feed. No server or database is required to serve the finished site. The source checkout contains no example catalog or demo artwork. Run the builder before serving `site/` locally; `site/data/projects.json` and `site/feed.xml` are generated outputs.

## Deploy the site

1. Put the contents of this project at the root of the public GitHub repository (including `.github/workflows/pages.yml`). The workflow expects the publishing branch to be `main`.
2. Under **Settings → Pages**, select **GitHub Actions** as the build and deployment source.
3. Optionally connect a private configuration repository as described below. Without one, the build uses the public defaults and scans the public repository owner's account.
4. Run **Actions → Update catalog and deploy Pages → Run workflow**. A push to `main` also triggers a build.

The workflow installs Python dependencies and ImageMagick, runs the tests, generates `site/data/projects.json` and `site/feed.xml`, checks the public output, and deploys `site/` to GitHub Pages.

### GitHub Actions settings

Configure these under **Settings → Secrets and variables → Actions** in the **public** repository. Settings for the private repositories are optional.

| Name | Kind | Purpose |
| --- | --- | --- |
| `PRIVATE_CONFIG_REPOSITORY` | Variable | Private configuration repository in `OWNER/REPO` format |
| `PRIVATE_CONFIG_REPO_TOKEN` | Secret | Fine-grained token with **Contents: read** permission for that repository |
| `CATALOG_CACHE_REPOSITORY` | Variable | Separate private repository for durable generated thumbnails and RSS history |
| `CATALOG_CACHE_TOKEN` | Secret | Fine-grained token with **Contents: read/write** permission for the cache repository only |
| `CATALOG_SITE_URL` | Variable | Full published HTTPS base URL, particularly for a custom domain or nonstandard site path |
| `YOUTUBE_CHANNEL_ID` | Variable or secret | Optional YouTube channel ID or handle for automatic video matching |
| `YOUTUBE_API_KEY` | Secret | Optional YouTube Data API key for discovery and availability checks |
| `IGDB_CLIENT_ID` | Secret | Optional IGDB client ID |
| `IGDB_CLIENT_SECRET` | Secret | Optional IGDB client secret |
| `CATALOG_SITE_JSON` | Variable | Optional JSON object overriding individual site branding fields |
| `CATALOG_PLATFORM_COLORS_JSON` | Variable | Optional JSON object overriding the platform color mapping |

`GITHUB_TOKEN` and repository identity are provided automatically by GitHub Actions. The private configuration token does not need write permission. Keep tokens in Actions secrets, not in committed JSON files.

## Configure discovery and game metadata

`config.json` contains operational defaults. An optional private `config.json` overrides only the sections and keys it supplies. Site identity, social links, and labels belong in **`branding.json`**, not in `config.json`.

Example private `config.json`:

```json
{
  "discovery": {
    "owners": ["example-owner"],
    "exclude_repositories": ["example-owner/catalog-site"]
  },
  "updates": {"flags": 3},
  "overrides": {
    "example-owner/example-game": {
      "title": "Example Game",
      "platforms": ["PS1"],
      "igdb_query": "Example Game",
      "youtube_match_titles": ["Example Game English Patch"]
    }
  }
}
```

The publisher automatically excludes its own repository when `GITHUB_REPOSITORY` is set. You can still add explicit exclusions for other repositories.

### Discovery settings

| Key under `discovery` | Behavior |
| --- | --- |
| `owners` | GitHub users or organizations whose public repositories are scanned |
| `include_all_owner_repos` | Include all public repositories from selected owners rather than filtering by topic or description |
| `include_topics_any` | Topic keywords used when filtering owner repositories |
| `include_description_matches` | Text phrases used when filtering repository names/descriptions |
| `include_repositories` | Explicit `OWNER/REPO` inclusions |
| `exclude_repositories` | Explicit `OWNER/REPO` exclusions, applied even to otherwise included repositories |
| `include_forks` | Permit forked repositories; defaults to `false` |
| `search_queries` | Additional GitHub repository search queries |
| `search_results_per_query` | Maximum results requested for each search query |
| `max_projects` | Maximum number of indexed projects |

Projects are discovered from GitHub's public repository metadata. The `overrides` object is keyed by `OWNER/REPO` and can supply corrected titles, platforms, descriptions, cover images, external links, YouTube aliases, and IGDB lookup information. Overrides **do not manufacture a GitHub release or replace the actual `status.txt`-based status**. Use `youtube_urls` (an array of up to 10 video URLs) to override the list from a repository's `assets/youtube.txt`.

Available enrichment controls include `igdb.enabled`, `igdb.use_summaries`, `external_links.enabled`, `youtube.enabled`, `youtube.channel`, `youtube.max_videos`, `youtube.max_per_game`, and `thumbnails.enabled`, `thumbnails.width`, `thumbnails.quality`, `thumbnails.max_source_bytes`. Their default values are in the public [`config.json`](config.json).

### Updated dates

`updates.flags` is a bitmask. Combine event types by adding their values:

| Value | Updated-date event |
| --- | --- |
| `1` | Published GitHub releases |
| `2` | Changes to root `status.txt` |
| `4` | Asset changes |
| `8` | Any commit |

The default is `3`, meaning **releases plus status changes**. When no configured event has occurred, the site uses the repository's first commit date, or its creation date if it has no commits. A release's actual publication time is tracked separately for the Recent releases carousel.

## Organize a game repository

The catalog can discover the following files in the public game repositories it indexes:

```text
example-game/
  status.txt
  assets/
    cover.png
    description.txt
    youtube.txt
    screenshot-01.png
    screenshots/
      screenshot-02.webp
```

- **`status.txt`**: `In-Progress` or `Paused`. A published GitHub Release takes precedence and shows the game as **Released**. Missing or invalid status defaults to In-Progress.
- **`assets/cover.png`**: Optional cover artwork. Other supported cover filenames are defined in `scripts/build.py`. If no cover is present, the builder may use IGDB artwork or available screenshots.
- **`assets/description.txt`**: Optional game description, preferred over automatically sourced descriptions. Explicit per-game description overrides take precedence.
- **`assets/youtube.txt`**: Up to 10 YouTube URLs, one per line. Additional videos can be matched from the configured YouTube channel.
- **Screenshots**: PNG, JPEG, or WebP images in `assets/` (including subdirectories), `screenshots/`, and `docs/screenshots/`. The builder indexes up to 32 per game.

The catalog can use Wikipedia, IGDB, and MobyGames for descriptions, covers, and reference links when available. These services are optional and results can be adjusted with per-game overrides.

## Customize the website

Place these files in the **private configuration repository**, not in the public website repository:

```text
config.json
branding.json
platform-colors.json
about.md
theme.css
assets/
  logo.png
  favicon.png
  rss.svg
  rss_light.svg
  rss_dark.svg
  github.svg
  github_light.svg
  github_dark.svg
  discord.svg
  discord_light.svg
  discord_dark.svg
  bluesky.svg
  bluesky_light.svg
  bluesky_dark.svg
  kofi.svg
  kofi_light.svg
  kofi_dark.svg
```

The `assets/` SVG files are all optional. The other theme names follow the same `name.svg`, `name_light.svg`, `name_dark.svg` pattern. Root-level `theme.css` is an optional CSS override; `platform-colors.json` maps platform names to `{ "background": "#RRGGBB", "text": "#RRGGBB" }`.

Example `branding.json`:

```json
{
  "site": {
    "name": "My Game Catalog",
    "description": "Game projects and releases",
    "tagline": "Unofficial game translations",
    "github_url": "https://github.com/example-owner",
    "discord_url": "https://discord.gg/example-invite",
    "bluesky_url": "https://bsky.app/profile/example.bsky.social",
    "kofi_url": "https://ko-fi.com/example",
    "kofi_label": "Support the project",
    "theme_color_dark": "#100e20",
    "theme_color_light": "#f2f6f5"
  }
}
```

The header order is **About, RSS, GitHub, Discord, Bluesky, Ko-fi, theme control**. Discord, Bluesky, and Ko-fi appear only when their corresponding URL is configured. Each social link uses its matching theme SVG if present, otherwise its base SVG, and finally a plain-text label if no usable SVG exists. Icons use a common **24px height** while preserving natural width. SVGs must be static and self-contained; scripts and external resource references are rejected.

The root-level `about.md` supplies the About page. It may be empty or omitted, in which case the page has no article content. The builder renders supported Markdown into `about.html`; source Markdown and private JSON are not copied into the public site. Images referenced inside Markdown must have publicly reachable URLs or published asset paths.

## Visitor features

- **Recent releases**: Up to 10 games with published Alpha, Beta, or full releases; five covers visible on desktop, with the selected cover enlarged and centered when possible. It advances automatically and supports pointer dragging, touch swipes, and the draggable position track. Details open below the covers only when the selected card is clicked.
- **Catalog**: Search, platform and status filters, sorting, and an **All / Screenshots only / Videos only / Both / None** media filter. Filters can be shared through the URL. Search controls become sticky beneath the header when reached on desktop.
- **Cards**: Published versions appear on the covers; Alpha/Beta tags are shown where applicable. Clicking a card slides its details open or closed. The linked version in details leads to its GitHub release page.
- **Media viewer**: Screenshot and video galleries open when the visitor selects them and support thumbnail and keyboard navigation.
- **RSS**: `feed.xml` announces published releases and actual status transitions. The RSS link appears in the header and feed-reader discovery metadata.

### RSS URL and history

The RSS URL is the published website's base URL plus `/feed.xml`. For a GitHub user site it is `https://USER.github.io/feed.xml`; for a project site it is `https://USER.github.io/REPOSITORY/feed.xml`. Set `CATALOG_SITE_URL` for a custom domain or nonstandard base path.

The builder retains up to 100 recent feed entries and uses stable identifiers to avoid repeating release notifications. It reads earlier feed and catalog data from the deployed site, with the optional private cache as a fallback. Routine commits and media changes do not create RSS entries. An existing deployment is needed to preserve history across stateless builds unless the private cache is configured.

## Automation and caching

`.github/workflows/pages.yml` runs on pushes to `main`, manual dispatch, `source_updated` repository dispatch, and a five-minute cron schedule. Scheduled runs perform a lightweight check first and only rebuild when a relevant source or configuration change is detected. GitHub may delay scheduled runs.

Before publication the workflow validates the generated `site/` directory with `python -m scripts.publish_guard site`. The **only uploaded Actions artifact** is the verified public Pages site. Raw private configuration and cache state must not be published as artifacts.

### Optional private cache repository

The private cache is separate from the private branding repository. Create a private Git repository and set `CATALOG_CACHE_REPOSITORY` and `CATALOG_CACHE_TOKEN` as described above. It stores:

```text
state/
  thumbnail-manifest.json
  thumbnails/
  rss/
    feed.xml
    projects.json
```

The workflow reads this cache only for full builds, and commits updated state **after successful Pages deployment** on the same runner. There is no need to change GitHub Actions cache settings or use a cross-job cache artifact. The site also builds without a cache repository.

For correctness, thumbnail reuse is tied to Git blob identities and verified cached file hashes. Screenshots removed from the source repository are omitted from future builds, and unused generated thumbnails are pruned. YouTube links are freshly validated when building and are not restored from cached video lists. Scheduled checks also sample published videos for confirmed removal; detection and successful redeployment are required before a removed video disappears from the static site. Without `YOUTUBE_API_KEY`, availability checking uses a more conservative method.

### Workflow history

The `prune-history` job keeps the **20 newest runs of this catalog workflow**, plus any still-active runs, and deletes older completed runs and their logs/artifacts. The cleanup uses the built-in `GITHUB_TOKEN` with `actions: write`; it does not modify other workflows. A cleanup failure does not block deployment. Deletions are permanent, and a five-minute schedule can make the retained history relatively short.

## Local development

The deployment workflow installs a current Python 3.x interpreter. Install Python dependencies and ImageMagick (either the `magick` or `convert` command must be available):

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

To build with a local checkout of private configuration and an explicit GitHub account:

```bash
export CATALOG_PRIVATE_CONFIG_DIR="/path/to/private-config"
export GITHUB_OWNER="example-owner"
export GITHUB_TOKEN="YOUR_GITHUB_TOKEN"
python -m scripts.build
python -m http.server 8080 -d site
```

Open `http://localhost:8080/` to inspect the generated site. The token is optional for public GitHub API calls, but authenticated access is recommended to avoid low rate limits. `CATALOG_PRIVATE_CONFIG_DIR` and the optional `CATALOG_CACHE_DIR` are local directory paths, not repository URLs. Never commit private checkouts or tokens into the public repository.
