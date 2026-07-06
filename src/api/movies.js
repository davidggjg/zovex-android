const MOVIES_URL_PRIMARY =
  'https://raw.githubusercontent.com/davidggjg/zovex-android/main/public/movies.json';
const MOVIES_URL_FALLBACK =
  'https://raw.githubusercontent.com/davidggjg/zovex/main/public/movies.json';
const LIVE_URL =
  'https://raw.githubusercontent.com/davidggjg/zovex/main/public/live.json';
const BACKEND_URL = 'https://davidhzhdhd-my-telegram-bot.hf.space';

let _moviesCache = null;
let _moviesCacheTime = 0;
const CACHE_MS = 5 * 60 * 1000;

export async function fetchMovies() {
  const now = Date.now();
  if (_moviesCache && now - _moviesCacheTime < CACHE_MS) return _moviesCache;
  try {
    const primary = await fetch(MOVIES_URL_PRIMARY + '?t=' + now);
    if (primary.ok) {
      const data = await primary.json();
      if (Array.isArray(data) && data.length > 0) {
        _moviesCache = data;
        _moviesCacheTime = now;
        return data;
      }
    }
  } catch {}
  try {
    const fallback = await fetch(MOVIES_URL_FALLBACK + '?t=' + now);
    if (!fallback.ok) throw new Error('fetch failed');
    const data = await fallback.json();
    _moviesCache = data;
    _moviesCacheTime = now;
    return data;
  } catch {
    return _moviesCache || [];
  }
}

export async function fetchLiveChannels() {
  try {
    const res = await fetch(LIVE_URL + '?t=' + Date.now());
    if (!res.ok) throw new Error('failed');
    const data = await res.json();
    // Support both array format and {channels:[...]} format
    if (Array.isArray(data)) return data;
    if (Array.isArray(data.channels)) return data.channels;
    if (data.url) return [{id: 'live_main', title: 'שידור חי', video_url: data.url, type: 'direct'}];
    return [];
  } catch {
    return [];
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
