const MAIN_SITE_ORIGIN = 'https://zovex.duckdns.org';
// /content/lite = אותו קטלוג בלי שדה ה-description הכבד (הכי גדול), עם ETag
// ותמיכה ב-?limit לציור מיידי. הגרסה הקודמת משכה את /content המלא עם ?t=<now>
// שמבטל כל caching — כל טעינה הורידה מגהבייטים מחדש. התיאור נמשך לפי דרישה
// (fetchItemDetail) כשפותחים סרט. זהה בדיוק לזרימה של האתר.
const LITE_URL = 'https://zovex.duckdns.org/content/lite';
const ITEM_URL = 'https://zovex.duckdns.org/content/item/';
const BACKEND_URL = 'https://zovex.duckdns.org';

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

function _mapImages(raw) {
  return raw.map(m => (m && m.thumbnail_url ? {...m, thumbnail_url: resolveImage(m.thumbnail_url)} : m));
}

// הקטלוג המלא (בלי description — נמשך לפי דרישה). בלי ?t=<now> כדי שה-ETag
// של השרת יעבוד: אחרי הפעם הראשונה השרת מחזיר 304 והלקוח משתמש ב-cache.
export async function fetchMovies() {
  const now = Date.now();
  if (_moviesCache && now - _moviesCacheTime < CACHE_MS) return _moviesCache;
  try {
    const res = await fetch(LITE_URL);
    if (!res.ok) throw new Error('fetch failed');
    const raw = await res.json();
    const data = _mapImages(raw);
    _moviesCache = data;
    _moviesCacheTime = now;
    return data;
  } catch {
    return _moviesCache || [];
  }
}

// ציור ראשון מהיר: 800 הפריטים החדשים ביותר בלבד. משמש לפריים הראשון של
// מסך הבית; ברקע קוראים ל-fetchMovies() כדי להשלים את השאר. לא נכתב ל-cache
// כדי לא לדרוס את הקטלוג המלא.
export async function fetchMoviesFast() {
  try {
    const res = await fetch(LITE_URL + '?limit=800');
    if (!res.ok) throw new Error('fetch failed');
    const raw = await res.json();
    return _mapImages(raw);
  } catch {
    return _moviesCache || [];
  }
}

// פריט בודד עם ה-description המלא, נמשך כשפותחים סרט. השרת מחזיר Cache-Control
// max-age=300, אז פתיחות חוזרות מיידיות.
export async function fetchItemDetail(id) {
  if (!id) return null;
  try {
    const res = await fetch(ITEM_URL + encodeURIComponent(id));
    if (!res.ok) throw new Error('fetch failed');
    const m = await res.json();
    if (m && m.thumbnail_url) m.thumbnail_url = resolveImage(m.thumbnail_url);
    return m;
  } catch {
    return null;
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

// ── Support / feedback ───────────────────────────────────────────────────────
// גרסת האפליקציה. חייבת להתאים ל-versionName ב-build.gradle. השרת משווה אליה
// כדי להחליט אם צריך לכפות עדכון.
// חייבת להתאים ל-versionName ב-build.gradle. היא עמדה על 1.0.22 בעוד
// ה-gradle כבר על 1.0.24 — שתי גרסאות פער, כלומר האפליקציה דיווחה על
// עצמה מספר שאינו נכון והשוואת הגרסאות מול השרת התבססה עליו.
export const APP_VERSION = '1.0.30';

export async function sendFeedback({userId, name, email, text, kind}) {
  if (!userId || !text) return false;
  const res = await apiCall('/feedback/send', 'POST', {
    user_id: userId, name: name || '', email: email || '',
    text, kind: kind || 'support',
  });
  return !!res;
}

export async function fetchMyFeedback(userId) {
  if (!userId) return {messages: []};
  const res = await apiCall(`/feedback/mine?user_id=${encodeURIComponent(userId)}`, 'GET');
  return res || {messages: []};
}

// משווה שתי גרסאות "x.y.z". מחזיר -1/0/1.
export function cmpVersion(a, b) {
  const pa = String(a || '0').split('.').map(n => parseInt(n, 10) || 0);
  const pb = String(b || '0').split('.').map(n => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0, y = pb[i] || 0;
    if (x < y) return -1;
    if (x > y) return 1;
  }
  return 0;
}

// מחזיר {latest,min,url,notes} או null אם אין חיבור.
export async function fetchAppVersion() {
  return apiCall('/app/version', 'GET');
}
