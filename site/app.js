/* Game Catalog. Static site with release metadata published during catalog builds. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const state = {
    projects: [], search: params.get('q') || '', platform: params.get('platform') || 'all',
    status: ['all','Released','Paused','In-Progress'].includes(params.get('status')) ? params.get('status') : 'all',
    media: ['all','screenshots','videos','both','none'].includes(params.get('media')) ? params.get('media') : 'all',
    sort: ['recent', 'az', 'oldest', 'stars'].includes(params.get('sort')) ? params.get('sort') : 'recent',
    visible: 12, expanded: null, selectedMedia: null, showcaseProjects: [], showcaseIndex: 0, showcaseDetailsOpen: false, showcaseSelectedMedia: null, platformColors: {}, themeColors: {dark: '#151b21', light: '#f2f5f7'}
  };
  const escape = value => String(value ?? '').replace(/[&<>"']/g,
    char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const safeUrl = value => {
    try { if (!value) return ''; const url = new URL(String(value), location.href); return ['https:', 'http:'].includes(url.protocol) ? url.href : ''; }
    catch { return ''; }
  };
  const socialIconSources = {};
  const socialIconGeneration = {};
  function updateSocialIcons(theme) {
    for (const service of ['rss', 'github', 'discord', 'bluesky', 'kofi']) {
      const link = el(service === 'kofi' ? 'support-link' : `nav-${service}`);
      const img = el(`${service}-icon`);
      const label = link.querySelector('.social-link-text');
      const sources = socialIconSources[service] || {};
      const candidates = [...new Set([sources[theme], sources.base].filter(Boolean))];
      const generation = (socialIconGeneration[service] || 0) + 1;
      socialIconGeneration[service] = generation;
      let nextIndex = 0;
      img.hidden = true;
      label.hidden = false;
      link.classList.remove('is-icon');
      function attemptNext() {
        if (socialIconGeneration[service] !== generation) return;
        if (nextIndex >= candidates.length) {
          img.removeAttribute('src');
          return;
        }
        const url = candidates[nextIndex++];
        img.onload = () => {
          if (socialIconGeneration[service] !== generation || img.getAttribute('src') !== url) return;
          img.hidden = false;
          label.hidden = true;
          link.classList.add('is-icon');
        };
        img.onerror = () => {
          if (socialIconGeneration[service] === generation && img.getAttribute('src') === url) attemptNext();
        };
        img.src = url;
      }
      attemptNext();
    }
  }
  function configureSocialIcons(site) {
    for (const service of ['rss', 'github', 'discord', 'bluesky', 'kofi']) {
      socialIconSources[service] = {
        base: safeUrl(site[`${service}_icon_url`]),
        light: safeUrl(site[`${service}_icon_light_url`]),
        dark: safeUrl(site[`${service}_icon_dark_url`])
      };
    }
    updateSocialIcons(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
  }
  const normalize = value => String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const initials = name => (String(name || 'Game').match(/[\p{L}\p{N}]+/gu) || ['GA']).slice(0, 2).map(word => word[0]).join('').toUpperCase();
  const tone = title => [...String(title || '')].reduce((total, char) => (total + char.codePointAt(0)) % 6, 0);
  const shortDate = value => {
    const date = value ? new Date(value) : new Date(NaN);
    return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('en', {month:'short', day:'numeric', year:'numeric', timeZone:'UTC'}).format(date) : 'No tracked update';
  };
  const starIcon = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none"><path d="m12 2 3.2 6.7 7.3 1-5.3 5.2 1.3 7.1L12 18.6l-6.5 3.4 1.3-7.1-5.3-5.2 7.3-1L12 2Z" stroke="currentColor" stroke-width="1.6"/></svg>';

  function youtubeId(link) {
    try {
      const u = new URL(String(link));
      if (u.protocol !== 'https:' || u.username || u.password || u.port) return '';
      let id = '';
      if (['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'].includes(u.hostname)) {
        if (u.pathname === '/watch') id = u.searchParams.get('v') || '';
        else if (/^\/(shorts|embed|live)\//.test(u.pathname)) id = u.pathname.split('/')[2] || '';
      } else if (['youtu.be','www.youtu.be'].includes(u.hostname)) id = u.pathname.slice(1);
      return /^[a-zA-Z0-9_-]{11}$/.test(id) ? id : '';
    } catch { return ''; }
  }

  function galleryFor(p) {
    const gallery = [];
    const seenVideos = new Set();
    const addVideo = (id, title) => {
      if (!id || seenVideos.has(id)) return;
      seenVideos.add(id);
      gallery.push({id:`video-${id}`, type:'video', src:`https://www.youtube.com/watch?v=${id}`,
        poster:`https://i.ytimg.com/vi/${id}/hqdefault.jpg`, videoId:id, title:title || 'Project video'});
    };
    const explicitVideos = Array.isArray(p.youtube_urls) ? p.youtube_urls : [];
    explicitVideos.forEach(url => addVideo(youtubeId(url), 'Project video'));
    (Array.isArray(p.youtube_videos) ? p.youtube_videos : []).forEach(v => {
      if (v && typeof v === 'object') addVideo(youtubeId(v.url), String(v.title || 'Channel video'));
    });
    let shots = (Array.isArray(p.screenshots) ? p.screenshots : []).map(safeUrl).filter(Boolean);
    if (!shots.length && p.cover_source !== 'igdb' && safeUrl(p.cover_url)) shots = [safeUrl(p.cover_url)];
    shots.forEach((src, index) => {
      const preview = Array.isArray(p.screenshot_thumbnails)
        ? safeUrl(p.screenshot_thumbnails[index]) : '';
      const dimensions = Array.isArray(p.screenshot_dimensions) ? p.screenshot_dimensions[index] : null;
      const width = Number(dimensions?.[0]);
      const height = Number(dimensions?.[1]);
      gallery.push({id:`image-${index}`, type:'image', src, poster:preview || src,
        width: width > 0 && Number.isFinite(width) ? width : 0,
        height: height > 0 && Number.isFinite(height) ? height : 0});
    });
    return gallery;
  }

  // Classify exactly what appears in the card's expandable media gallery.
  // Screenshots and Videos are exclusive categories; Both and None cover the
  // remaining two combinations. Channel videos are included.
  function mediaCategory(p) {
    const gallery = galleryFor(p);
    const hasScreenshots = gallery.some(item => item.type === 'image');
    const hasVideos = gallery.some(item => item.type === 'video');
    if (hasScreenshots && hasVideos) return 'both';
    if (hasScreenshots) return 'screenshots';
    if (hasVideos) return 'videos';
    return 'none';
  }

  function placeholder(p) {
    return `<div class="poster poster-tone-${tone(p.title)}" aria-hidden="true"><span class="poster-glyph">${escape(initials(p.title))}</span><span class="poster-name">${escape(p.title)}</span></div>`;
  }

  function platformStyle(name) {
    // Validate all CSS values, even though data is generated by our build.
    const fallback = {background:'#3b484e', text:'#ffffff'};
    const colors = state.platformColors[name] || state.platformColors.Other || fallback;
    const hex = value => /^#[0-9a-fA-F]{6}$/.test(String(value || ''));
    const bg = hex(colors.background) ? colors.background : fallback.background;
    const fg = hex(colors.text) ? colors.text : fallback.text;
    return `style="--platform-bg:${bg};--platform-fg:${fg}"`;
  }

  function platformBadges(p, className) {
    return `<span class="platform-badges ${className}">${projectPlatforms(p).map(name =>
      `<span class="platform-badge" ${platformStyle(name)}>${escape(name)}</span>`).join('')}</span>`;
  }

  function releaseStage(p) {
    // Stage is derived only from the most recent published release tag.
    if (p.status !== 'Released' || !p.release_tag) return '';
    const stage = String(p.release_stage || '').toUpperCase();
    if (stage === 'ALPHA' || stage === 'BETA') return stage;
    return '';
  }

  function statusLabel(p) {
    const stage = releaseStage(p);
    return `${p.status || 'Project'}${stage ? ` [${stage}]` : ''}`;
  }

  // Use the same normalized version text in details and on the card cover.
  // A separate stage badge on the card provides the [ALPHA]/[BETA] qualifier.
  function versionBaseLabel(p) {
    const tag = String(p.release_tag || '');
    const stage = releaseStage(p);
    if (!stage) return tag;
    // Avoid displaying a simple stage suffix twice, while preserving
    // qualifiers such as `beta.2` or other meaningful tag components.
    const suffix = new RegExp(`([\\d]|[-._\\s])${stage}$`, 'i');
    let base = tag.replace(suffix, (_, separator) => /\d/.test(separator) ? separator : '');
    base = base.replace(new RegExp(`^${stage}[-._\\s]+`, 'i'), '');
    return base || tag;
  }

  function versionLabel(p) {
    const base = versionBaseLabel(p);
    const stage = releaseStage(p);
    return stage ? `${base} [${stage}]` : base;
  }

  // Release links never pin the tag captured during the last catalog build.
  // GitHub's /releases/latest excludes prereleases, so use the release list for
  // a prerelease and /releases/latest for a full release.
  function releaseDestination(p) {
    if (p.status !== 'Released' || !p.release_tag) return '';
    const match = /^([a-zA-Z0-9_.-]+)\/([a-zA-Z0-9_.-]+)$/.exec(String(p.repo || ''));
    if (!match) return safeUrl(p.release_url); // Use the release URL if the repository name is unavailable.
    const base = `https://github.com/${match[1]}/${match[2]}/releases`;
    return p.release_prerelease || releaseStage(p) ? base : `${base}/latest`;
  }

  function projectCard(p) {
    const cover = safeUrl(p.cover_url);
    const active = state.expanded === p.id;
    const stage = releaseStage(p);
    const hasRelease = p.status === 'Released' && Boolean(p.release_tag);
    const label = active ? `Close details for ${p.title}` : `Expand details for ${p.title}`;
    return `<article class="project-card ${active ? 'is-expanded' : ''}" data-project="${escape(p.id)}">
      <button type="button" class="card-open" data-open="${escape(p.id)}" aria-expanded="${active}" ${active ? `aria-controls="expanded-details"` : ''} aria-label="${escape(label)}">
        <div class="project-image">
          ${cover ? `<img src="${escape(cover)}" alt="" loading="lazy">` : placeholder(p)}
          ${hasRelease ? `<div class="release-labels">
            ${stage ? `<span class="release-stage-badge" data-stage="${stage}">${stage}</span>` : ''}
            <span class="release-version-badge" title="${escape(versionLabel(p))}">${escape(versionBaseLabel(p))}</span>
          </div>` : ''}
          ${platformBadges(p, 'image-platform')}
        </div>
        <div class="project-body">
          <p class="card-kicker">${p.updated_at ? `Updated ${escape(shortDate(p.updated_at))}` : 'No tracked update'}</p>
          <h2>${escape(p.title)}</h2>
          <p class="card-description">${escape(p.description || p.game_description || '')}</p>
          <div class="card-footer">
            <span class="card-footer-left"><span class="stars" aria-label="${Number(p.stars) || 0} GitHub stars, read only">${starIcon} ${Number(p.stars) || 0}</span>
            <span class="card-status" data-status="${escape(p.status)}">${escape(statusLabel(p))}</span></span>
            <span class="card-action">${active ? 'Close' : 'Details'} <span aria-hidden="true">${active ? '−' : '+'}</span></span>
          </div>
        </div>
      </button>
    </article>`;
  }

  // Reserve a frame for the tallest aspect ratio in the entire gallery.
  // Lower width/height ratios need more vertical space. This is deliberately
  // independent of the selected item, so carousel navigation cannot resize it.
  // The CSS then fits each image within that frame without clipping its edges.
  function viewerAspect(gallery) {
    const ratios = gallery.map(item => {
      if (item.type === 'video') return 16 / 9;
      return item.width > 0 && item.height > 0 ? item.width / item.height : 4 / 3;
    });
    return Math.max(0.65, Math.min(2.5, Math.min(...ratios)));
  }

  function viewerMarkup(p, media, gallery, viewerId = 'detail-viewer') {
    // Do not construct a viewer until a thumbnail has been selected.
    if (!gallery.length || !media) return '';
    const isVideo = media.type === 'video';
    const index = media ? gallery.findIndex(item => item.id === media.id) : -1;
    const navigation = gallery.length > 1 && media ? `
      <button type="button" class="viewer-nav viewer-prev" data-media-step="-1" aria-label="Previous media" title="Previous media (Left arrow)">
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none"><path d="m15 5-7 7 7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
      <button type="button" class="viewer-nav viewer-next" data-media-step="1" aria-label="Next media" title="Next media (Right arrow)">
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none"><path d="m9 5 7 7-7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>` : '';
    const content = isVideo
      ? `<div class="video-aspect"><iframe title="${escape(media.title || `Video for ${p.title}`)}" src="https://www.youtube.com/embed/${media.videoId}?rel=0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen loading="lazy"></iframe></div>`
      : `<img class="viewer-image" src="${escape(media.src)}" alt="Full-resolution screenshot for ${escape(p.title)}">`;
    const aspect = viewerAspect(gallery);
    return `<div class="detail-viewer" id="${viewerId}" tabindex="-1" role="region" aria-label="Media viewer">
      <div class="viewer-toolbar"><strong>${!media ? 'Media' : (isVideo ? 'Video' : 'Screenshot')} <span class="viewer-counter" aria-live="polite">${index < 0 ? '0' : index + 1} / ${gallery.length}</span></strong>
        <div><a class="viewer-source-link" ${media ? `href="${escape(media.src)}" target="_blank" rel="noopener noreferrer"` : 'aria-hidden="true" tabindex="-1"'}>${isVideo ? 'Watch on YouTube' : 'View original resolution'}</a>
        <button type="button" data-close-viewer="true" aria-label="Close media viewer">Close ×</button></div>
      </div>
      <div class="viewer-stage" style="--viewer-aspect:${aspect}">${content}${navigation}</div>
    </div>`;
  }

  function detailContents(p, selectedMedia = null, showcase = false) {
    const media = galleryFor(p);
    const selected = media.find(item => item.id === selectedMedia);
    const thumbnails = media.map((item, index) => {
      const active = selected && selected.id === item.id;
      const label = item.type === 'video' ? `Play ${item.title}` : `View screenshot ${index + 1}`;
      return `<button type="button" data-media="${escape(item.id)}" class="media-thumb ${active ? 'selected' : ''}" aria-label="${escape(label)}" aria-pressed="${Boolean(active)}">
          <img src="${escape(item.poster || item.src)}" alt="" loading="lazy">
          ${item.type === 'video' ? `<span class="play-icon" aria-hidden="true">▶</span><span class="media-kind">VIDEO</span>` : `<span class="media-kind">${String(index + 1).padStart(2,'0')}</span>`}
        </button>`;
    }).join('');
    const repoUrl = safeUrl(p.github_url);
    const releaseUrl = releaseDestination(p);
    const sourceUrl = safeUrl(p.description_source_url);
    const igdbUrl = safeUrl(p.igdb_url);
    const wikipediaUrl = safeUrl(p.wikipedia_url);
    const mobygamesUrl = safeUrl(p.mobygames_url);
    const title = repoUrl ? `<a href="${escape(repoUrl)}" target="_blank" rel="noopener noreferrer">${escape(p.title)}</a>` : escape(p.title);
    const version = releaseUrl && p.release_tag ? `<span class="detail-download"><span class="download-label">Download</span><a class="version-link" href="${escape(releaseUrl)}" target="_blank" rel="noopener noreferrer" title="Open GitHub Release">${escape(versionLabel(p))}</a></span>` : '<span class="version-missing">No release</span>';
    const hostId = showcase ? 'showcase-media-viewer-host' : 'media-viewer-host';
    return `<div class="expanded-details-inner">
      <div id="${hostId}" class="media-viewer-host" ${selected ? '' : 'hidden'}>${viewerMarkup(p, selected, media, showcase ? 'showcase-detail-viewer' : 'detail-viewer')}</div>
      <div class="detail-panel">
        <div class="detail-media">
          <h3>MEDIA <span>${media.length ? media.length : '0'}</span></h3>
          <div class="thumbnail-list" aria-label="Game screenshots and video">${thumbnails || '<p class="no-media">No screenshots or video are available for this game yet.</p>'}</div>
        </div>
        <div class="detail-info">
          <div class="detail-title-row">${platformBadges(p, 'detail-platform')}<h3>${title}</h3>${version}</div>
          <div class="description-eyebrow">ABOUT THE GAME</div>
          <p class="game-description">${escape(p.game_description || p.description || 'No game description has been provided.')}</p>
          ${sourceUrl ? (p.description_source === 'Wikipedia'
            ? `<div class="description-credit">Excerpt adapted from <a href="${escape(sourceUrl)}" target="_blank" rel="noopener noreferrer">Wikipedia contributors</a>, licensed under <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener noreferrer">CC BY-SA 4.0</a> (shortened for display).</div>`
            : `<a class="description-source" href="${escape(sourceUrl)}" target="_blank" rel="noopener noreferrer">Description source</a>`) : ''}
          <div class="detail-metadata"><span class="card-status" data-status="${escape(p.status || 'Project')}">${escape(statusLabel(p))}</span><span>${p.updated_at ? `Last updated ${escape(shortDate(p.updated_at))}` : 'No tracked update'}</span></div>
          <div class="detail-footer"><div class="detail-footer-links">${repoUrl ? `<a href="${escape(repoUrl)}" target="_blank" rel="noopener noreferrer">Repository</a>` : ''}${p.cover_source === 'igdb' && igdbUrl ? `<a href="${escape(igdbUrl)}" target="_blank" rel="noopener noreferrer">Cover from IGDB</a>` : ''}${mobygamesUrl ? `<a href="${escape(mobygamesUrl)}" target="_blank" rel="noopener noreferrer">MobyGames</a>` : ''}${wikipediaUrl ? `<a href="${escape(wikipediaUrl)}" target="_blank" rel="noopener noreferrer">Wikipedia</a>` : ''}</div><button type="button" data-close-project="true">Close details ↑</button></div>
        </div>
      </div>
    </div>`;
  }

  function detailsPanel(p) {
    return `<section id="expanded-details" class="expanded-details" aria-label="Details for ${escape(p.title)}" aria-hidden="true" inert>${detailContents(p, state.selectedMedia)}</section>`;
  }

  function columnCount() {
    return window.matchMedia('(max-width: 540px)').matches ? 1 :
      window.matchMedia('(max-width: 760px)').matches ? 2 :
      window.matchMedia('(max-width: 960px)').matches ? 3 : 4;
  }

  function projectPlatforms(project) {
    return Array.isArray(project.platforms)
      ? [...new Set(project.platforms.filter(Boolean))] : [];
  }

  function filteredProjects() {
    const query = normalize(state.search.trim());
    const filtered = state.projects.filter(p => {
      if (state.platform !== 'all' && !projectPlatforms(p).includes(state.platform)) return false;
      if (state.status !== 'all' && p.status !== state.status) return false;
      if (state.media !== 'all' && mediaCategory(p) !== state.media) return false;
      return !query || normalize([p.title, p.repo, p.description, p.game_description, p.platform, p.status, ...(p.topics || [])].join(' ')).includes(query);
    });
    filtered.sort((a,b) => {
      if (state.sort === 'az') return (a.title || '').localeCompare(b.title || '');
      if (state.sort === 'stars') return (+b.stars || 0) - (+a.stars || 0) || a.title.localeCompare(b.title);
      if (state.sort === 'oldest') return (a.updated_at || '').localeCompare(b.updated_at || '');
      return (b.updated_at || '').localeCompare(a.updated_at || '');
    });
    return filtered;
  }

  function syncQuery() {
    const url = new URL(location.href);
    for (const key of ['q','platform','status','media','sort']) url.searchParams.delete(key);
    if (state.search) url.searchParams.set('q', state.search);
    if (state.platform !== 'all') url.searchParams.set('platform', state.platform);
    if (state.status !== 'all') url.searchParams.set('status', state.status);
    if (state.media !== 'all') url.searchParams.set('media', state.media);
    if (state.sort !== 'recent') url.searchParams.set('sort', state.sort);
    history.replaceState(null, '', url);
  }

  // The showcase is independent of catalog filters and always displays up to
  // ten genuine published releases, newest publication first.
  function recentReleases() {
    const ranked = state.projects.filter(p => p.status === 'Released' && Boolean(p.release_tag));
    const stamp = p => {
      const ms = Date.parse(p.release_published_at || '');
      return Number.isFinite(ms) ? ms : -Infinity;
    };
    ranked.sort((a, b) => stamp(b) - stamp(a) || String(a.title || '').localeCompare(String(b.title || '')));
    return ranked.slice(0, 10);
  }

  function showcaseCard(p, index) {
    const cover = safeUrl(p.cover_url);
    const stage = releaseStage(p);
    return `<article class="showcase-slide" data-showcase-slide="${index}" aria-hidden="true">
      <button type="button" class="showcase-cover" data-showcase-select="${index}" tabindex="-1" aria-label="${index === 0 ? 'Toggle details for' : 'Select'} ${escape(p.title)} in recent releases" aria-controls="showcase-detail" aria-expanded="false">
        <div class="project-image">
          ${cover ? `<img src="${escape(cover)}" alt="" draggable="false" loading="${index === 0 ? 'eager' : 'lazy'}">` : placeholder(p)}
          <div class="release-labels">${stage ? `<span class="release-stage-badge" data-stage="${stage}">${stage}</span>` : ''}
            <span class="release-version-badge">${escape(versionBaseLabel(p))}</span></div>
          ${platformBadges(p, 'image-platform')}
        </div>
        <div class="project-body">
          <p class="card-kicker">${p.release_published_at ? `Released ${escape(shortDate(p.release_published_at))}` : `Updated ${escape(shortDate(p.updated_at))}`}</p>
          <h3>${escape(p.title)}</h3>
          <div class="card-footer"><span class="card-status" data-status="Released">${escape(statusLabel(p))}</span><span class="card-action">Details <span class="showcase-toggle-mark" aria-hidden="true">+</span></span></div>
        </div>
      </button>
    </article>`;
  }

  // Featured and regular cards render the same details markup, including the
  // media sidebar, full viewer, description, release link, and footer.
  function showcaseDetails(p) {
    return detailContents(p, state.showcaseSelectedMedia, true);
  }

  let showcaseTimer = null;
  let showcaseDragging = false;
  let showcaseHovered = false;
  let showcaseLastWheel = 0;
  let showcaseSwipeSuppressUntil = 0;
  const showcaseIntervalMs = 7000;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  // Five simultaneous cards on desktop, up to three on tablets and two on
  // narrow phones. Keep the selected card in slot 3 where possible, then
  // allow it to approach the edges at the ends of the ten-release list.
  function showcaseWindow(index, total, slots) {
    const count = Math.min(total, slots);
    const start = Math.max(0, Math.min(index - Math.floor(count / 2), total - count));
    return {start, count};
  }

  function layoutShowcase(initial = false) {
    const stage = el('showcase-stage');
    if (!stage || !state.showcaseProjects.length) return;
    const slides = [...el('showcase-track').querySelectorAll('.showcase-slide')];
    const width = slides[0]?.offsetWidth || 290;
    const height = slides[0]?.offsetHeight || width * 11 / 8.5;
    const stageWidth = stage.clientWidth;
    const stageHeight = stage.clientHeight;
    const narrow = stageWidth < 460;
    const tablet = stageWidth < 760;
    const mobileLayout = narrow || tablet;
    const slots = narrow ? 2 : tablet ? 3 : 5;
    const {start, count} = showcaseWindow(state.showcaseIndex, slides.length, slots);
    const inset = mobileLayout ? 12 : 18;
    const gap = mobileLayout ? 10 : 12;
    const available = stageWidth - 2 * inset - width - gap * (count - 1);
    const smallScale = mobileLayout ? Math.min(.68, Math.max(.28, available / (Math.max(1, count - 1) * width)))
      : Math.min(.72, Math.max(.28, available / (Math.max(1, count - 1) * width)));
    const smallWidth = width * smallScale;
    const rowWidth = width + (count - 1) * (smallWidth + gap);
    let x = Math.max(inset, (stageWidth - rowWidth) / 2);
    const coords = new Map();
    for (let slot = 0; slot < count; slot++) {
      const i = start + slot;
      const scale = i === state.showcaseIndex ? 1 : smallScale;
      coords.set(i, {x, scale});
      x += width * scale + gap;
    }
    const bottom = 16;
    slides.forEach((slide, i) => {
      const visible = coords.has(i);
      const active = i === state.showcaseIndex;
      const scale = active ? 1 : smallScale;
      const x = visible ? coords.get(i).x : i < start ? -width - gap : stageWidth + gap;
      const y = stageHeight - bottom - height * scale;
      if (initial) slide.classList.add('showcase-no-transition');
      slide.style.transform = `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0) scale(${scale})`;
      slide.style.opacity = visible ? '1' : '0';
      slide.style.zIndex = active ? '2' : '1';
      slide.style.pointerEvents = visible ? 'auto' : 'none';
      slide.classList.toggle('is-active', active);
      slide.setAttribute('aria-hidden', visible ? 'false' : 'true');
      const button = slide.querySelector('button');
      button.tabIndex = visible ? 0 : -1;
      button.setAttribute('aria-expanded', String(active && state.showcaseDetailsOpen));
      button.setAttribute('aria-label', `${active ? (state.showcaseDetailsOpen ? 'Close' : 'Open') + ' details for' : 'Select'} ${state.showcaseProjects[i].title}`);
      const mark = slide.querySelector('.showcase-toggle-mark');
      if (mark) mark.textContent = active && state.showcaseDetailsOpen ? '−' : '+';
    });
    if (initial) requestAnimationFrame(() => slides.forEach(slide => slide.classList.remove('showcase-no-transition')));
  }

  function setShowcaseDetailsOpen(open) {
    state.showcaseDetailsOpen = Boolean(open);
    if (!open) {
      state.showcaseSelectedMedia = null;
      const viewer = el('showcase-media-viewer-host');
      if (viewer) { viewer.replaceChildren(); viewer.hidden = true; }
    }
    const detail = el('showcase-detail');
    detail.classList.toggle('is-open', state.showcaseDetailsOpen);
    detail.setAttribute('aria-hidden', String(!state.showcaseDetailsOpen));
    detail.inert = !state.showcaseDetailsOpen;
    layoutShowcase();
    syncShowcaseTimer();
  }

  function updateShowcase(initial = false) {
    const projects = state.showcaseProjects;
    if (!projects.length) return;
    layoutShowcase(initial);
    const drawer = el('showcase-detail');
    drawer.innerHTML = showcaseDetails(projects[state.showcaseIndex]);
    drawer.setAttribute('aria-label', `Details for ${projects[state.showcaseIndex].title}`);
    el('showcase-position').textContent = `${state.showcaseIndex + 1} / ${projects.length}`;
    el('showcase-dots').querySelectorAll('[data-showcase-go]').forEach((dot, index) => {
      const active = index === state.showcaseIndex;
      dot.classList.toggle('is-active', active);
      dot.setAttribute('aria-current', active ? 'true' : 'false');
    });
  }

  function stopShowcaseTimer() {
    if (showcaseTimer !== null) { clearInterval(showcaseTimer); showcaseTimer = null; }
  }

  function syncShowcaseTimer() {
    stopShowcaseTimer();
    if (!state.showcaseProjects.length || state.showcaseProjects.length < 2 || showcaseDragging ||
        showcaseHovered || state.showcaseDetailsOpen || document.hidden || reducedMotion.matches ||
        el('release-showcase').querySelector(':focus-visible')) return;
    showcaseTimer = setInterval(() => selectShowcase(state.showcaseIndex + 1, false), showcaseIntervalMs);
  }

  function selectShowcase(index, manual = true) {
    const n = state.showcaseProjects.length;
    if (!n) return;
    const next = (index % n + n) % n;
    if (next !== state.showcaseIndex) {
      // Keep an already-open details panel mounted, with no collapse/reveal
      // transition. Only replace its content and unload the previous media.
      state.showcaseSelectedMedia = null;
      state.showcaseIndex = next;
      updateShowcase();
    }
    if (manual) syncShowcaseTimer();
  }

  function setupShowcase() {
    state.showcaseProjects = recentReleases();
    state.showcaseIndex = 0;
    state.showcaseDetailsOpen = false;
    state.showcaseSelectedMedia = null;
    const root = el('release-showcase');
    root.hidden = state.showcaseProjects.length === 0;
    if (root.hidden) return;
    const drawer = el('showcase-detail');
    drawer.inert = true;
    drawer.setAttribute('aria-hidden', 'true');
    drawer.classList.remove('is-open');
    el('showcase-track').innerHTML = state.showcaseProjects.map(showcaseCard).join('');
    el('showcase-dots').innerHTML = state.showcaseProjects.map((p, i) =>
      `<button type="button" data-showcase-go="${i}" aria-label="Show release ${i + 1}: ${escape(p.title)}" aria-current="${i === 0 ? 'true' : 'false'}"><span aria-hidden="true"></span></button>`).join('');
    // Reduced-motion preference disables automatic cycling, with no on-page
    // pause/play control. Dragging and keyboard navigation still work.
    updateShowcase(true);
    syncShowcaseTimer();
  }

  function attachShowcaseEvents() {
    const root = el('release-showcase');
    const stage = el('showcase-stage');
    const dots = el('showcase-dots');
    root.addEventListener('click', event => {
      const dot = event.target.closest('[data-showcase-go]');
      if (dot) { selectShowcase(Number(dot.dataset.showcaseGo)); return; }
      if (Date.now() < showcaseSwipeSuppressUntil) return;
      const slide = event.target.closest('[data-showcase-select]');
      if (slide) {
        const selected = Number(slide.dataset.showcaseSelect);
        if (selected === state.showcaseIndex) setShowcaseDetailsOpen(!state.showcaseDetailsOpen);
        else selectShowcase(selected);
        return;
      }
      const step = event.target.closest('[data-media-step]');
      if (step) { stepMedia(Number(step.dataset.mediaStep), true, true); return; }
      const media = event.target.closest('[data-media]');
      if (media) {
        state.showcaseSelectedMedia = media.dataset.media;
        refreshMediaViewer(null, true);
        return;
      }
      if (event.target.closest('[data-close-viewer]')) {
        const previous = state.showcaseSelectedMedia;
        state.showcaseSelectedMedia = null;
        refreshMediaViewer(null, true);
        const thumbnails = el('showcase-detail')?.querySelectorAll('.media-thumb') || [];
        [...thumbnails].find(button => button.dataset.media === previous)?.focus({preventScroll:true});
        return;
      }
      if (event.target.closest('[data-close-project]')) setShowcaseDetailsOpen(false);
    });
    root.addEventListener('focusin', syncShowcaseTimer);
    root.addEventListener('focusout', () => requestAnimationFrame(syncShowcaseTimer));
    stage.addEventListener('mouseenter', () => { showcaseHovered = true; syncShowcaseTimer(); });
    stage.addEventListener('mouseleave', () => { showcaseHovered = false; syncShowcaseTimer(); });
    stage.addEventListener('keydown', event => {
      if (event.altKey || event.metaKey || event.ctrlKey) return;
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        event.preventDefault(); event.stopPropagation();
        selectShowcase(state.showcaseIndex + (event.key === 'ArrowRight' ? 1 : -1));
      } else if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault(); event.stopPropagation();
        selectShowcase(event.key === 'Home' ? 0 : state.showcaseProjects.length - 1);
      }
    });

    // Drag the cover row with a mouse or a finger. The selected item follows
    // the gesture, and is clamped at both ends rather than wrapping on drag.
    // A real drag must never trigger the active card's click-to-open drawer.
    let cardDrag = null;
    const finishCardDrag = event => {
      if (!cardDrag || cardDrag.id !== event.pointerId) return;
      if (cardDrag.dragging) {
        showcaseSwipeSuppressUntil = Date.now() + 450;
        stage.classList.remove('is-dragging');
        showcaseDragging = false;
        syncShowcaseTimer();
      }
      cardDrag = null;
    };
    stage.addEventListener('dragstart', event => event.preventDefault());
    stage.addEventListener('pointerdown', event => {
      if (!event.isPrimary || event.button !== 0) return;
      cardDrag = {id:event.pointerId, x:event.clientX, y:event.clientY,
        index:state.showcaseIndex, dragging:false};
    });
    stage.addEventListener('pointermove', event => {
      if (!cardDrag || cardDrag.id !== event.pointerId) return;
      const dx = event.clientX - cardDrag.x;
      const dy = event.clientY - cardDrag.y;
      if (!cardDrag.dragging) {
        if (Math.abs(dx) < 12 || Math.abs(dx) <= Math.abs(dy) * 1.15) return;
        cardDrag.dragging = true;
        showcaseDragging = true;
        stage.classList.add('is-dragging');
        stage.setPointerCapture(event.pointerId);
        syncShowcaseTimer();
      }
      const distancePerCard = Math.max(48, Math.min(140, stage.clientWidth / 7));
      const steps = Math.round(-dx / distancePerCard);
      const last = state.showcaseProjects.length - 1;
      const index = Math.max(0, Math.min(last, cardDrag.index + steps));
      if (index !== state.showcaseIndex) selectShowcase(index);
    });
    stage.addEventListener('pointerup', finishCardDrag);
    stage.addEventListener('pointercancel', finishCardDrag);
    stage.addEventListener('lostpointercapture', finishCardDrag);

    // The indicator row is a draggable scrubber, not just a set of dots.
    // Fixed-width slots prevent its geometry from shifting as an active dot
    // widens. Clicking any dot and dragging across them selects immediately.
    const selectDotAt = clientX => {
      const buttons = [...dots.querySelectorAll('[data-showcase-go]')];
      let closest = 0, distance = Infinity;
      buttons.forEach((button, i) => {
        const rect = button.getBoundingClientRect();
        const delta = Math.abs(clientX - (rect.left + rect.width / 2));
        if (delta < distance) { closest = i; distance = delta; }
      });
      if (buttons.length) selectShowcase(closest);
    };
    let scrubPointer = null;
    dots.addEventListener('pointerdown', event => {
      if (!event.isPrimary || event.button !== 0) return;
      scrubPointer = event.pointerId;
      showcaseDragging = true;
      dots.classList.add('is-dragging');
      dots.setPointerCapture(event.pointerId);
      selectDotAt(event.clientX);
      syncShowcaseTimer();
    });
    dots.addEventListener('pointermove', event => {
      if (scrubPointer === event.pointerId) selectDotAt(event.clientX);
    });
    const finishScrub = event => {
      if (scrubPointer !== event.pointerId) return;
      selectDotAt(event.clientX);
      scrubPointer = null;
      showcaseDragging = false;
      dots.classList.remove('is-dragging');
      if (dots.hasPointerCapture(event.pointerId)) dots.releasePointerCapture(event.pointerId);
      syncShowcaseTimer();
    };
    dots.addEventListener('pointerup', finishScrub);
    dots.addEventListener('pointercancel', finishScrub);
    dots.addEventListener('lostpointercapture', event => {
      if (scrubPointer === event.pointerId) {
        scrubPointer = null;
        showcaseDragging = false;
        dots.classList.remove('is-dragging');
        syncShowcaseTimer();
      }
    });
    stage.addEventListener('wheel', event => {
      // Preserve vertical page scroll. Horizontal trackpad wheels browse releases.
      if (Math.abs(event.deltaX) < 25 || Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return;
      event.preventDefault();
      if (Date.now() - showcaseLastWheel < 500) return;
      showcaseLastWheel = Date.now();
      selectShowcase(state.showcaseIndex + (event.deltaX > 0 ? 1 : -1));
    }, {passive:false});
    document.addEventListener('visibilitychange', syncShowcaseTimer);
    reducedMotion.addEventListener?.('change', syncShowcaseTimer);
    window.addEventListener('resize', () => layoutShowcase(true));
  }

  // Regular grid cards use the same slide/reveal transition as the release
  // carousel. Leave the closing panel in the DOM until its collapse finishes;
  // otherwise replacing innerHTML would make closing instantaneous.
  let expandedCloseSequence = 0;
  let pendingExpandedAnimation = false;
  function openExpandedCard(id) {
    expandedCloseSequence++;
    state.expanded = id;
    state.selectedMedia = null;
    pendingExpandedAnimation = true;
    render();
    pendingExpandedAnimation = false;
    const panel = el('expanded-details');
    if (!panel) return;
    // Measure the collapsed state before changing classes, so both grid rows
    // and content opacity animate even on a freshly inserted panel.
    void panel.offsetHeight;
    requestAnimationFrame(() => {
      if (panel.isConnected && state.expanded === id) {
        panel.classList.add('is-open');
        panel.removeAttribute('aria-hidden');
        panel.inert = false;
        panel.scrollIntoView({block:'nearest', behavior:'smooth'});
      }
    });
  }

  // Switching between cards in an already-expanded grid row replaces only
  // the details content. The row itself stays open, so there is no closing or
  // opening transition and no half-second delay before the new game appears.
  function switchExpandedCardInRow(nextId) {
    const displayed = filteredProjects().slice(0, state.visible);
    const previousIndex = displayed.findIndex(project => project.id === state.expanded);
    const nextIndex = displayed.findIndex(project => project.id === nextId);
    const cols = columnCount();
    if (previousIndex < 0 || nextIndex < 0 ||
        Math.floor(previousIndex / cols) !== Math.floor(nextIndex / cols)) return false;
    const panel = el('expanded-details');
    if (!panel || !panel.classList.contains('is-open')) return false;

    ++expandedCloseSequence;
    const previousId = state.expanded;
    const nextProject = displayed[nextIndex];
    state.expanded = nextId;
    state.selectedMedia = null;

    // Keep the existing outer panel and its open grid track in place. This
    // also removes any playing media from the previously selected game.
    const template = document.createElement('template');
    template.innerHTML = detailsPanel(nextProject);
    const replacement = template.content.firstElementChild;
    panel.replaceChildren(...replacement.children);
    panel.setAttribute('aria-label', replacement.getAttribute('aria-label'));
    panel.removeAttribute('aria-hidden');
    panel.inert = false;

    for (const card of el('project-grid').querySelectorAll('.project-card')) {
      if (card.dataset.project !== previousId && card.dataset.project !== nextId) continue;
      const selected = card.dataset.project === nextId;
      card.classList.toggle('is-expanded', selected);
      const button = card.querySelector('[data-open]');
      if (button) {
        button.setAttribute('aria-expanded', String(selected));
        button.setAttribute('aria-label', `${selected ? 'Close details for' : 'Expand details for'} ${selected ? nextProject.title : displayed[previousIndex].title}`);
        if (selected) button.setAttribute('aria-controls', 'expanded-details');
        else button.removeAttribute('aria-controls');
      }
      const action = card.querySelector('.card-action');
      if (action) action.innerHTML = selected
        ? 'Close <span aria-hidden="true">−</span>'
        : 'Details <span aria-hidden="true">+</span>';
    }
    return true;
  }

  function closeExpandedCard(nextId = null) {
    if (nextId && state.expanded && switchExpandedCardInRow(nextId)) return;
    if (!state.expanded) {
      if (nextId) openExpandedCard(nextId);
      return;
    }
    const panel = el('expanded-details');
    state.expanded = null;
    state.selectedMedia = null;
    const sequence = ++expandedCloseSequence;
    if (!panel) { render(); if (nextId) openExpandedCard(nextId); return; }
    // Stop active video playback immediately, without keeping an iframe in
    // the collapsing content until the animation has finished.
    const host = panel.querySelector('#media-viewer-host');
    if (host) { host.replaceChildren(); host.hidden = true; }
    panel.classList.remove('is-open');
    panel.setAttribute('aria-hidden', 'true');
    panel.inert = true;
    let finished = false;
    const complete = () => {
      if (finished || sequence !== expandedCloseSequence) return;
      finished = true;
      if (nextId) openExpandedCard(nextId);
      else render();
    };
    // The timeout also handles backgrounded tabs, missing transition events,
    // and reduced-motion preferences without leaving a stale drawer in place.
    panel.addEventListener('transitionend', event => {
      if (event.target === panel && event.propertyName === 'grid-template-rows') complete();
    });
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) complete();
    else window.setTimeout(complete, 560);
  }

  function render() {
    const matches = filteredProjects();
    const displayed = matches.slice(0, state.visible);
    if (state.expanded && !displayed.some(p => p.id === state.expanded)) { state.expanded = null; state.selectedMedia = null; }
    let markup = '';
    const cols = columnCount();
    displayed.forEach((p, index) => {
      markup += projectCard(p);
      if (state.expanded && (index + 1) % cols === 0) {
        const open = displayed.find(item => item.id === state.expanded);
        if (open && displayed.indexOf(open) >= index + 1 - cols && displayed.indexOf(open) <= index) markup += detailsPanel(open);
      }
    });
    if (state.expanded && displayed.length % cols) {
      const open = displayed.find(item => item.id === state.expanded);
      if (open && displayed.indexOf(open) >= displayed.length - displayed.length % cols) markup += detailsPanel(open);
    }
    el('project-grid').innerHTML = markup;
    // Filters, resizing and Show More can re-render while details are open.
    // Restore the open state without hiding the pane from keyboard users.
    const stillOpen = el('expanded-details');
    if (stillOpen && state.expanded && !pendingExpandedAnimation) {
      stillOpen.classList.add('is-open');
      stillOpen.removeAttribute('aria-hidden');
      stillOpen.inert = false;
    }
    el('project-grid').setAttribute('aria-busy', 'false');
    el('empty-state').hidden = matches.length > 0;
    el('more-row').hidden = matches.length <= state.visible;
    el('more-count').textContent = `(${matches.length - state.visible} remaining)`;
    el('clear-filters').hidden = !state.search && state.platform === 'all' && state.status === 'all' && state.media === 'all' && state.sort === 'recent';
    dropdowns.platform?.sync();
    syncQuery();
  }

  // Release versions, stages, and status are read only from the shared,
  // build-generated data/projects.json snapshot. The browser never queries
  // api.github.com and does not maintain a per-user release metadata cache.

  function setupPlatforms() {
    const counts = new Map();
    state.projects.forEach(p => projectPlatforms(p).forEach(platform =>
      counts.set(platform, (counts.get(platform) || 0) + 1)));
    const platforms = [...counts].sort(([a, na],[b,nb]) => nb - na || a.localeCompare(b));
    el('platform-menu').innerHTML = `<div role="option" id="platform-option-all" data-value="all" data-label="All platforms" aria-selected="false">All platforms</div>` +
      platforms.map(([name, count], index) => `<div role="option" id="platform-option-${index}" data-value="${escape(name)}" data-label="${escape(name)}" aria-selected="false">${escape(name)} <span class="option-count">${count}</span></div>`).join('');
    if (!counts.has(state.platform)) state.platform = 'all';
  }

  // Custom select menus keep the same sharp-cornered styling on every browser.
  // A focused listbox supplies native-like arrow, Home, End, Enter and Escape behavior.
  const dropdowns = {};
  function setupDropdown(name, stateKey, change) {
    const wrap = el(`${name}-dropdown`);
    const trigger = el(name === 'sort' ? 'sort' : `${name}-filter`);
    const menu = el(`${name}-menu`);
    const valueLabel = el(`${name}-value`);
    const options = [...menu.querySelectorAll('[role="option"]')];
    let activeIndex = 0;

    function sync() {
      const index = Math.max(0, options.findIndex(option => option.dataset.value === state[stateKey]));
      activeIndex = index;
      valueLabel.textContent = options[index].dataset.label || options[index].textContent;
      options.forEach((option, i) => option.setAttribute('aria-selected', String(i === index)));
    }
    function close(restoreFocus = false) {
      menu.hidden = true;
      wrap.classList.remove('is-open');
      trigger.setAttribute('aria-expanded', 'false');
      if (restoreFocus) trigger.focus({preventScroll:true});
    }
    function highlight(index) {
      activeIndex = (index + options.length) % options.length;
      options.forEach((option, i) => option.classList.toggle('is-active', i === activeIndex));
      menu.setAttribute('aria-activedescendant', options[activeIndex].id);
      options[activeIndex].scrollIntoView({block:'nearest'});
    }
    function open(index = null) {
      Object.values(dropdowns).forEach(dropdown => dropdown.close());
      sync();
      menu.hidden = false;
      wrap.classList.add('is-open');
      trigger.setAttribute('aria-expanded', 'true');
      highlight(index === null ? activeIndex : index);
      menu.focus({preventScroll:true});
    }
    function choose(index) {
      change(options[index].dataset.value);
      sync();
      close(true);
    }

    trigger.addEventListener('click', () => menu.hidden ? open() : close(true));
    trigger.addEventListener('keydown', event => {
      if (['ArrowDown', 'ArrowUp', 'Home', 'End', ' ', 'Enter'].includes(event.key)) {
        event.preventDefault();
        const index = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
          : event.key === 'ArrowDown' ? activeIndex + 1 : event.key === 'ArrowUp' ? activeIndex - 1 : activeIndex;
        open(index);
      }
    });
    menu.addEventListener('keydown', event => {
      let index = null;
      if (event.key === 'ArrowDown') index = activeIndex + 1;
      else if (event.key === 'ArrowUp') index = activeIndex - 1;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = options.length - 1;
      else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(activeIndex); return; }
      else if (event.key === 'Escape') { event.preventDefault(); close(true); return; }
      else if (event.key === 'Tab') { close(); return; }
      else if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) {
        const start = (activeIndex + 1) % options.length;
        const matched = options.findIndex((option, i) =>
          (i >= start && option.textContent.trim().toLowerCase().startsWith(event.key.toLowerCase())));
        index = matched >= 0 ? matched : options.findIndex(option => option.textContent.trim().toLowerCase().startsWith(event.key.toLowerCase()));
      }
      if (index !== null && index >= 0) { event.preventDefault(); highlight(index); }
    });
    menu.addEventListener('click', event => {
      const option = event.target.closest('[role="option"]');
      if (option && menu.contains(option)) choose(options.indexOf(option));
    });
    document.addEventListener('pointerdown', event => { if (!wrap.contains(event.target)) close(); });
    dropdowns[name] = {sync, close};
    sync();
  }

  function resetFilters() {
    state.search = ''; state.platform = 'all'; state.status = 'all'; state.media = 'all'; state.sort = 'recent'; state.visible = 12;
    state.expanded = null; state.selectedMedia = null;
    el('search').value = ''; dropdowns.status.sync(); dropdowns.media.sync(); dropdowns.sort.sync(); dropdowns.platform?.sync();
    render();
  }

  function applySiteSettings(data) {
    const site = data.site || {};
    const name = String(site.name || 'Game Catalog');
    const logo = safeUrl(site.logo_url);
    el('brand-logo').hidden = !logo;
    if (logo) el('brand-logo').src = logo;
    el('brand-logo').alt = name;
    document.querySelector('.brand-tagline').textContent = String(site.tagline || 'Game projects and releases');
    const themeUrl = safeUrl(site.theme_url);
    if (themeUrl) {
      const customTheme = document.createElement('link');
      customTheme.rel = 'stylesheet';
      customTheme.href = themeUrl;
      document.head.appendChild(customTheme);
    }
    const favicon = safeUrl(site.favicon_url);
    if (favicon) {
      el('site-favicon').href = favicon;
      el('site-favicon').type = favicon.toLowerCase().split('?')[0].endsWith('.svg') ? 'image/svg+xml' : 'image/png';
      el('site-apple-icon').href = favicon;
    }
    const discord = el('nav-discord');
    const discordUrl = safeUrl(site.discord_url);
    let validDiscordInvite = '';
    if (discordUrl) {
      const url = new URL(discordUrl);
      const host = url.hostname.toLowerCase();
      if (url.protocol === 'https:' && (
        (host === 'discord.gg' && /^\/[^/]+\/?$/.test(url.pathname)) ||
        ((host === 'discord.com' || host === 'discordapp.com') && /^\/invite\/[^/]+\/?$/.test(url.pathname))
      )) validDiscordInvite = discordUrl;
    }
    discord.hidden = !validDiscordInvite;
    if (validDiscordInvite) discord.href = validDiscordInvite;
    const bluesky = el('nav-bluesky');
    const blueskyUrl = safeUrl(site.bluesky_url);
    let validBlueskyProfile = '';
    if (blueskyUrl) {
      const url = new URL(blueskyUrl);
      if (url.protocol === 'https:' && url.hostname.toLowerCase() === 'bsky.app' &&
          /^\/profile\/[^/]+\/?$/.test(url.pathname)) validBlueskyProfile = blueskyUrl;
    }
    bluesky.hidden = !validBlueskyProfile;
    if (validBlueskyProfile) bluesky.href = validBlueskyProfile;
    const support = el('support-link');
    const kofiUrl = safeUrl(site.kofi_url);
    support.hidden = !kofiUrl;
    if (kofiUrl) support.href = kofiUrl;
    const kofiLabel = String(site.kofi_label || 'Ko-fi');
    support.setAttribute('aria-label', kofiLabel);
    el('support-label').textContent = kofiLabel;
    el('footer-name').textContent = name;
    el('footer-year').textContent = new Date().getFullYear();
    document.title = `Games | ${name}`;
    document.querySelector('meta[name="description"]')?.setAttribute('content', String(site.description || 'Game projects, releases, screenshots, and videos.'));
    const owner = (data.owners || [])[0] || '';
    const profile = owner ? `https://github.com/${encodeURIComponent(owner)}` : '';
    const githubUrl = safeUrl(site.github_url) || profile;
    el('nav-github').hidden = !githubUrl;
    if (githubUrl) el('nav-github').href = githubUrl;
    configureSocialIcons(site);
    for (const theme of ['dark', 'light']) {
      const value = site[`theme_color_${theme}`];
      if (/^#[0-9a-fA-F]{6}$/.test(String(value || ''))) state.themeColors[theme] = value;
    }
    // Apply brand-provided theme metadata even if theme was set before catalog loaded.
    const activeTheme = document.documentElement.dataset.theme || 'dark';
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', state.themeColors[activeTheme] || state.themeColors.dark);
    state.platformColors = (data.platform_colors && typeof data.platform_colors === 'object' && !Array.isArray(data.platform_colors))
      ? data.platform_colors : {};
  }

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    updateSocialIcons(theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', state.themeColors[theme]);
    el('theme-toggle').setAttribute('aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    try { localStorage.setItem('game-catalog-theme', theme); } catch { /* blocked storage */ }
  }

  // Update only the viewer host and thumbnail state, never the expanded panel
  // or the game grid. Opening media is explicit; closing unloads the iframe or
  // image and hides the entire viewer, while leaving game details expanded.
  function refreshMediaViewer(focusDirection = null, showcase = false) {
    const project = showcase ? state.showcaseProjects[state.showcaseIndex] : state.projects.find(p => p.id === state.expanded);
    const host = el(showcase ? 'showcase-media-viewer-host' : 'media-viewer-host');
    if (!project || !host) return;
    const gallery = galleryFor(project);
    const selected = gallery.find(item => item.id === (showcase ? state.showcaseSelectedMedia : state.selectedMedia));
    const current = host.querySelector('.detail-viewer');
    if (!selected) {
      host.replaceChildren();
      host.hidden = true;
    } else {
      const template = document.createElement('template');
      template.innerHTML = viewerMarkup(project, selected, gallery, showcase ? 'showcase-detail-viewer' : 'detail-viewer').trim();
      const replacement = template.content.firstElementChild;
      if (replacement) {
        if (current) current.replaceWith(replacement);
        else host.append(replacement);
        host.hidden = false;
        if (focusDirection !== null) {
          replacement.querySelector(`[data-media-step="${focusDirection}"]`)?.focus({preventScroll:true});
        }
      }
    }
    el(showcase ? 'showcase-detail' : 'expanded-details')?.querySelectorAll('.media-thumb').forEach(button => {
      const active = button.dataset.media === (showcase ? state.showcaseSelectedMedia : state.selectedMedia);
      button.classList.toggle('selected', active);
      button.setAttribute('aria-pressed', String(active));
    });
  }

  // Navigate the combined sequence of videos and screenshots. Both ends wrap.
  function stepMedia(direction, focusNav = false, showcase = false) {
    if (showcase ? !state.showcaseDetailsOpen || !state.showcaseSelectedMedia : !state.expanded || !state.selectedMedia) return false;
    const project = showcase ? state.showcaseProjects[state.showcaseIndex] : state.projects.find(p => p.id === state.expanded);
    if (!project) return false;
    const gallery = galleryFor(project);
    if (gallery.length < 2) return false;
    const index = gallery.findIndex(item => item.id === (showcase ? state.showcaseSelectedMedia : state.selectedMedia));
    if (index < 0) return false;
    const nextId = gallery[(index + direction + gallery.length) % gallery.length].id;
    if (showcase) state.showcaseSelectedMedia = nextId;
    else state.selectedMedia = nextId;
    refreshMediaViewer(focusNav ? direction : null, showcase);
    return true;
  }

  function attachEvents() {
    attachShowcaseEvents();
    el('search').value = state.search;
    setupDropdown('status', 'status', value => { state.status = value; state.visible = 12; render(); });
    setupDropdown('media', 'media', value => { state.media = value; state.visible = 12; render(); });
    setupDropdown('sort', 'sort', value => { state.sort = value; render(); });
    el('search').addEventListener('input', e => { state.search = e.target.value; state.visible = 12; render(); });
    el('project-grid').addEventListener('click', e => {
      const step = e.target.closest('[data-media-step]');
      if (step) { stepMedia(Number(step.dataset.mediaStep), true); return; }
      const media = e.target.closest('[data-media]');
      if (media) {
        state.selectedMedia = media.dataset.media;
        refreshMediaViewer();
        return;
      }
      if (e.target.closest('[data-close-viewer]')) {
        const previous = state.selectedMedia;
        state.selectedMedia = null;
        refreshMediaViewer();
        // Return keyboard focus to the thumbnail that opened the viewer.
        const thumbnails = el('expanded-details')?.querySelectorAll('.media-thumb') || [];
        [...thumbnails].find(button => button.dataset.media === previous)?.focus({preventScroll:true});
        return;
      }
      if (e.target.closest('[data-close-project]')) { closeExpandedCard(); return; }
      const card = e.target.closest('[data-open]');
      if (card) {
        // Expanding a game must not automatically open its media viewer.
        state.selectedMedia = null;
        if (state.expanded === card.dataset.open) closeExpandedCard();
        else if (state.expanded) closeExpandedCard(card.dataset.open);
        else openExpandedCard(card.dataset.open);
      }
    });
    el('clear-filters').addEventListener('click', resetFilters);
    el('empty-reset').addEventListener('click', resetFilters);
    el('show-more').addEventListener('click', () => { state.visible += 12; render(); });
    el('theme-toggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
    document.addEventListener('keydown', e => {
      if (e.defaultPrevented) return;
      // Do not override arrows used for text editing or browser shortcuts.
      const typing = e.target.closest?.('input, select, textarea, [contenteditable="true"], [role="textbox"], [role="listbox"], [aria-haspopup="listbox"]');
      if (!e.defaultPrevented && !typing && !e.altKey && !e.ctrlKey && !e.metaKey &&
          (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
        const direction = e.key === 'ArrowLeft' ? -1 : 1;
        const inShowcase = Boolean(e.target.closest?.('#showcase-detail'));
        if (stepMedia(direction, false, inShowcase)) e.preventDefault();
      }
      if (e.key === '/' && !e.target.closest?.('[role="listbox"]') && !e.metaKey && !e.altKey && !e.ctrlKey && !['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)) { e.preventDefault(); el('search').focus(); }
      if (e.key === 'Escape' && state.showcaseSelectedMedia) {
        state.showcaseSelectedMedia = null;
        refreshMediaViewer(null, true);
      } else if (e.key === 'Escape' && e.target.closest?.('#showcase-detail') && state.showcaseDetailsOpen) {
        setShowcaseDetailsOpen(false);
      } else if (e.key === 'Escape' && state.selectedMedia) {
        state.selectedMedia = null; refreshMediaViewer();
      } else if (e.key === 'Escape' && state.expanded) { closeExpandedCard(); }
    });
    let currentCols = columnCount();
    window.addEventListener('resize', () => {
      const nextCols = columnCount();
      if (nextCols !== currentCols) { currentCols = nextCols; render(); }
    });
  }

  async function init() {
    attachEvents();
    try { setTheme(localStorage.getItem('game-catalog-theme') || 'dark'); } catch { setTheme('dark'); }
    try {
      const response = await fetch('./data/projects.json', {cache:'no-store'});
      if (!response.ok) throw Error(`HTTP ${response.status}`);
      const data = await response.json();
      state.projects = Array.isArray(data.projects) ? data.projects : [];
      applySiteSettings(data);
      setupPlatforms();
      setupDropdown('platform', 'platform', value => { state.platform = value; state.visible = 12; render(); });
      el('total-games').textContent = `${state.projects.length} ${state.projects.length === 1 ? 'Game' : 'Games'}`;
      render();
      setupShowcase();
    } catch (error) {
      console.error('Unable to load game catalog:', error);
      el('total-games').textContent = 'Catalog unavailable';
      el('project-grid').setAttribute('aria-busy','false');
      el('empty-state').hidden = false;
      el('empty-state').querySelector('h2').textContent = 'Catalog unavailable.';
      el('empty-state').querySelector('p').textContent = 'Serve the site through a local HTTP server or check data/projects.json.';
    }
  }
  init();
})();
