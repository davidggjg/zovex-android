const MOVIES_URL =
  'https://raw.githubusercontent.com/davidggjg/zovex/main/public/movies.json';

let _cache = null;
let _cacheTime = 0;
const CACHE_MS = 5 * 60 * 1000;

export async function fetchMovies() {
  const now = Date.now();
  if (_cache && now - _cacheTime < CACHE_MS) return _cache;
  try {
    const res = await fetch(MOVIES_URL + '?t=' + now);
    if (!res.ok) throw new Error('fetch failed');
    const data = await res.json();
    _cache = data;
    _cacheTime = now;
    return data;
  } catch (e) {
    if (_cache) return _cache;
    return [];
  }
}

export function clearCache() {
  _cache = null;
  _cacheTime = 0;
}
