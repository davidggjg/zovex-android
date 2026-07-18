const MAIN_SITE_ORIGIN = 'https://davidggjg.github.io';
const MOVIES_URL =
  'https://raw.githubusercontent.com/davidggjg/zovex/main/public/movies.json';
const BACKEND_URL = 'https://davidhzhdhd-my-telegram-bot.hf.space';

let _moviesCache = null;
let _moviesCacheTime = 0;
const CACHE_MS = 5 * 60 * 1000;

// Some thumbnail_url values (mainly live-channel logos) are root-relative
// paths like "/zovex/live-logos/kan11.png" - that's fine for the web app
// (same origin), but React Native's <Image> needs a real absolute URL or it
// just silently fails to load. Resolve any relative path against the main
// site's origin here, once, at the data layer, so every screen gets a
// working URL without needing to know about this quirk.
function resolveImage(url) {
  if (!url) return url;
  if (url.startsWith('http://') || url.startsWith('https://')) return url;
  if (url.startsWith('/')) return MAIN_SITE_ORIGIN + url;
  return url;
}

export async function fetchMovies() {
  const now = Date.now();
  if (_moviesCache && now - _moviesCacheTime < CACHE_MS) return _moviesCache;
  try {
    const res = await fetch(MOVIES_URL + '?t=' + now);
    if (!res.ok) throw new Error('fetch failed');
    const raw = await res.json();
    const data = raw.map(m => (m && m.thumbnail_url ? {...m, thumbnail_url: resolveImage(m.thumbnail_url)} : m));
    _moviesCache = data;
    _moviesCacheTime = now;
    return data;
  } catch {
    return _moviesCache || [];
  }
}

export function clearCache() {
  _moviesCache = null;
  _moviesCacheTime = 0;
}

// ── Backend API ──────────────────────────────────────────────────────────────

async function apiCall(path, method = 'GET', body = null, userId = null) {
  try {
    const headers = {'Content-Type': 'application/json'};
    if (userId) headers['x-user-id'] = userId;
    const res = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function saveProgress(mediaId, position, duration, userId) {
  if (!userId || !mediaId) return;
  await apiCall('/api/progress', 'POST', {media_id: mediaId, position, duration}, userId);
}

export async function loadProgress(mediaId, userId) {
  if (!userId || !mediaId) return 0;
  const res = await apiCall(`/api/progress/${mediaId}`, 'GET', null, userId);
  return res?.position || 0;
}

export async function saveHistory(mediaId, title, thumbnailUrl, userId) {
  if (!userId || !mediaId) return;
  await apiCall(
    '/api/history',
    'POST',
    {media_id: mediaId, title, thumbnail_url: thumbnailUrl || ''},
    userId,
  );
}

export async function fetchHistory(userId) {
  if (!userId) return [];
  const res = await apiCall('/api/history', 'GET', null, userId);
  return Array.isArray(res) ? res : [];
}
