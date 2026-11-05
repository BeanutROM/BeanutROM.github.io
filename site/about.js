/* About page: shared brand, support link, and light/dark theme with the catalog. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const colors = {dark:'#151b21', light:'#f2f5f7'};
  const safeUrl = value => {
    try {
      if (!value) return '';
      const url = new URL(String(value), location.href);
      return ['https:', 'http:'].includes(url.protocol) ? url.href : '';
    } catch { return ''; }
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
  function setTheme(theme) {
    if (!['dark', 'light'].includes(theme)) theme = 'dark';
    document.documentElement.dataset.theme = theme;
    updateSocialIcons(theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', colors[theme]);
    el('theme-toggle').setAttribute('aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    try { localStorage.setItem('game-catalog-theme', theme); } catch { /* blocked storage */ }
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
    document.title = `About | ${name}`;
    const owner = (data.owners || [])[0] || '';
    const profile = owner ? `https://github.com/${encodeURIComponent(owner)}` : '';
    const githubUrl = safeUrl(site.github_url) || profile;
    el('nav-github').hidden = !githubUrl;
    if (githubUrl) el('nav-github').href = githubUrl;
    configureSocialIcons(site);
    for (const theme of ['dark', 'light']) {
      const value = site[`theme_color_${theme}`];
      if (/^#[0-9a-fA-F]{6}$/.test(String(value || ''))) colors[theme] = value;
    }
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', colors[document.documentElement.dataset.theme || 'dark']);
    const count = Array.isArray(data.projects) ? data.projects.length : 0;
    el('total-games').textContent = `${count} ${count === 1 ? 'Game' : 'Games'}`;
  }
  async function init() {
    el('footer-year').textContent = new Date().getFullYear();
    el('theme-toggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
    try { setTheme(localStorage.getItem('game-catalog-theme') || 'dark'); } catch { setTheme('dark'); }
    try {
      const response = await fetch('./data/projects.json', {cache:'no-store'});
      if (!response.ok) throw Error(`HTTP ${response.status}`);
      applySiteSettings(await response.json());
    } catch (error) {
      console.error('Unable to load catalog branding for About page:', error);
      el('total-games').textContent = 'Games';
    }
  }
  init();
})();
