// לוח השידורים של ערוץ חי.
//
// השרת בונה אותו כל שעתיים מארבעה מקורות (וואלה, HOT, FreeTV, ותצלום של yes)
// ומגיש שתי צורות: קובץ קטן לכל ערוץ, וקובץ מלא עם כולם. הקטן הוא ~19KB
// והמלא ~1.8MB — פי תשעים — ולכן מנסים אותו קודם. הנפילה לקובץ המלא קיימת
// כדי שהאפליקציה תעבוד גם מול שרת שעוד לא מגיש את הקבצים הקטנים.
//
// הזמנים בקובץ הם epoch בשניות, כך שהחישוב של "מה עכשיו" נעשה מול השעון של
// המכשיר והלוח נשאר נכון גם בין בנייה לבנייה.

const BASE = 'https://zovex.duckdns.org';

// מטמון בזיכרון: המשתמש מדפדף בין ערוצים ואין טעם למשוך שוב באותה ישיבה.
const cache = new Map();
const TTL_MS = 10 * 60 * 1000;

export function channelSlug(ch) {
  if (!ch) return '';
  if (ch.custom_slug) return ch.custom_slug;
  const name = ch.title || ch.name || '';
  return encodeURIComponent(name.replace(/ /g, '-'));
}

async function getJson(url, ms) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(url, {signal: ctrl.signal});
    if (!r.ok) return null;
    return await r.json();
  } catch (_) {
    return null;
  } finally {
    clearTimeout(t);
  }
}

/** מחזיר מערך תוכניות ממוין, או [] אם אין לערוץ לוח. */
export async function fetchChannelSchedule(channel) {
  const slug = channelSlug(channel);
  if (!slug) return [];

  const hit = cache.get(slug);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.programs;

  let programs = null;
  const one = await getJson(`${BASE}/epg/${encodeURIComponent(slug)}.json`, 8000);
  if (one && Array.isArray(one.programs)) programs = one.programs;

  if (!programs) {
    const all = await getJson(`${BASE}/epg.json`, 20000);
    const entry = all && all.channels && all.channels[slug];
    programs = (entry && entry.programs) || [];
  }

  programs = programs
    .filter(p => p && typeof p.start === 'number' && typeof p.end === 'number')
    .sort((a, b) => a.start - b.start);
  cache.set(slug, {at: Date.now(), programs});
  return programs;
}

/** מפצל לתוכנית שרצה כרגע ולמה שעוד לפניה. */
export function splitNowNext(programs) {
  const now = Date.now() / 1000;
  const current = programs.find(p => p.start <= now && now < p.end) || null;
  const upcoming = programs.filter(p => p.end > now);
  return {current, upcoming};
}
