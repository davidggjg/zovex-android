// ── איך מגישים כתובת זרם ל-ExoPlayer ────────────────────────────────────────
//
// התקלה: ערוץ IPTV בכתובת מהצורה
//
//     http://host/<user>/<pass>/<id>
//
// לא התנגן בכלל. זו הצורה של פאנלי Xtream Codes, והיא הנפוצה ביותר
// בעולם ה-IPTV.
//
// הסיבה **אינה** ספרייה חסרה. ExoPlayer/Media3 שהאפליקציה כבר מביאה
// כולל את TsExtractor ומנגן MPEG-TS גולמי מצוין. הבעיה היא שאמרנו לו
// את הדבר הלא נכון: הקוד הקודם, בשלושת הנגנים, הניח שכל כתובת שידור חי
// בלי סיומת היא HLS —
//
//     return {uri, type: 'm3u8'};          // LiveMedia3Player
//     const liveHls = isLive && !NOT_HLS.test(curSrc);   // NativePlayer
//     const isHls = isLive || /\.m3u8|…/.test(src);      // TvNativePlayer
//
// ‎type:'m3u8'‎ גורם ל-ExoPlayer לבנות HlsMediaSource, שמתחיל בקריאת
// הפלייליסט ומצפה ל-‎#EXTM3U‎ בבתים הראשונים. נקודת קצה של Xtream בלי
// סיומת מגישה כברירת מחדל **MPEG-TS גולמי**, שמתחיל בבית 0x47. הפרסר
// נופל מיד, ולכן "לא מצליח לנגן" — בלי קשר לאיכות הזרם או לרשת.
//
// הפתרון כאן בשתי שכבות:
//
//   1. ניחוש ראשון טוב יותר. כתובת בצורת Xtream (שלושה מקטעים, האחרון
//      מספרי, בלי סיומת) מנוגנת קודם כזרם ישיר, ולא כ-HLS.
//   2. נפילה-אחורה שמתקנת את עצמה. כל כתובת מקבלת **רשימה** של דרכים
//      לנסות; הנגן מתקדם בה בכל onError. גם אם הניחוש הראשון שגוי,
//      הניסיון השני תופס. זה מה שהופך את זה לעמיד: אין צורך לנחש נכון,
//      רק לא להיתקע על ניחוש אחד.
//
// למה לא לבדוק את הבתים הראשונים לפני הניגון: ‎fetch‎ ב-React Native
// לא נותן גישה לגוף התשובה בזרימה, ו-‎res.text()‎ על זרם חי אינסופי
// שמתעלם מ-Range לא יחזור לעולם. נפילה-אחורה לפי onError משיגה את אותו
// דבר בלי הסיכון הזה.

// ‎VLC/3.0.20‎: לא קישוט. חלק משרתי ה-IPTV מחזירים 403 ל-User-Agent
// של OkHttp (ברירת המחדל של ExoPlayer) ומגישים רק ללקוחות שנראים כמו
// נגן אמיתי. NativePlayer כבר שלח את זה; LiveMedia3Player, שהוא הנגן
// שמשמש בפועל לשידור חי בטלפון, לא — וזו סיבת כישלון שנייה ובלתי
// תלויה לאותה כתובת בדיוק.
export const LIVE_UA = 'VLC/3.0.20 LibVLC/3.0.20';

const lastSegment = url => {
  const noQuery = String(url || '').split(/[?#]/)[0];
  const segs = noQuery.replace(/^[a-z]+:\/\/[^/]*/i, '').split('/').filter(Boolean);
  return {segs, last: segs[segs.length - 1] || ''};
};

const hasExt = name => /\.[a-z0-9]{2,5}$/i.test(name);

/**
 * האם הכתובת היא בצורת Xtream Codes — ‎/<user>/<pass>/<id>‎ בלי סיומת.
 * זו הצורה שכמעט תמיד מגישה MPEG-TS גולמי.
 */
export function isXtreamStyle(url) {
  const {segs, last} = lastSegment(url);
  if (!last || hasExt(last)) return false;
  if (!/^\d+$/.test(last)) return false;
  return segs.length >= 3;
}

/**
 * רשימת הדרכים לנסות לנגן, לפי סדר. כל איבר הוא ‎{url, type?}‎ —
 * **גם הכתובת יכולה להשתנות**, לא רק הסוג.
 *
 * למה הכתובת: בפאנלי Xtream, ‎/user/pass/id‎ החשוף לא תמיד מגיש את
 * הזרם בעצמו. הצורות שעובדות בפועל הן ‎…/id.m3u8‎ (HLS) ו-‎…/id.ts‎
 * (MPEG-TS), וחלק מהפאנלים מגישים **רק** איתן ומחזירים דף HTML או
 * הפניה על הכתובת החשופה. נגני IPTV מוסיפים את הסיומות האלה כדבר
 * שבשגרה, וזו הסיבה שאותו קישור "עובד ב-VLC ולא אצלנו".
 *
 * ‎type‎ חסר פירושו "בלי type" — ExoPlayer בונה ProgressiveMediaSource
 * ומריץ את ה-extractors שלו, שכוללים את TsExtractor. זה המסלול שמנגן
 * MPEG-TS גולמי.
 */
export function streamVariants(url) {
  const u = String(url || '');
  const {last} = lastSegment(u);

  if (/\.m3u8?(?:$|[?#])/i.test(u)) return [{url: u, type: 'm3u8'}, {url: u}];
  if (/\.mpd(?:$|[?#])/i.test(u)) return [{url: u, type: 'mpd'}];
  if (/\.ism|Manifest\.ism/i.test(u)) return [{url: u, type: 'ism'}, {url: u, type: 'm3u8'}];
  // מיכלים ישירים: קודם progressive, ו-HLS רק כגיבוי — יש שרתים
  // שמגישים פלייליסט מכתובת שנגמרת ב-.ts.
  if (/\.(?:ts|mpeg|mpg|mkv|avi|webm)(?:$|[?#])/i.test(u)) {
    return [{url: u}, {url: u, type: 'm3u8'}];
  }
  if (/\.(?:mp4|m4v|mov)(?:$|[?#])/i.test(u)) return [{url: u, type: 'mp4'}, {url: u}];

  // ── בלי סיומת ──────────────────────────────────────────────────────────
  // ‎withExt‎ שומר על ה-query string: בכתובות Xtream חתומות הוא נושא
  // טוקן, והדבקת הסיומת בסוף הכתובת כולה הייתה הורסת אותו.
  const withExt = ext => {
    const m = u.match(/^([^?#]*)(.*)$/);
    return (m ? m[1] : u).replace(/\/+$/, '') + ext + (m ? m[2] : '');
  };

  if (isXtreamStyle(u)) {
    return [
      {url: u},                              // TS גולמי על הכתובת החשופה
      {url: withExt('.m3u8'), type: 'm3u8'},  // הצורה הסטנדרטית ל-HLS
      {url: withExt('.ts')},                  // הצורה הסטנדרטית ל-TS
      {url: u, type: 'm3u8'},                 // HLS על הכתובת החשופה
    ];
  }

  if (!hasExt(last)) {
    // לא Xtream: נשאר HLS ראשון כדי לא לשבור ערוצים שכבר עובדים,
    // אבל עם אותן דרכים נוספות אחריו.
    return [
      {url: u, type: 'm3u8'},
      {url: u},
      {url: withExt('.m3u8'), type: 'm3u8'},
    ];
  }

  return [{url: u}, {url: u, type: 'm3u8'}];
}

/**
 * ה-source המלא לניסיון מספר [attempt], או null כשנגמרו הדרכים — כדי
 * שהנגן יעבור לנגן הבא בשרשרת במקום להסתובב.
 */
export function buildStreamSource(url, attempt = 0, {isLive = false, extra = {}} = {}) {
  const variants = streamVariants(url);
  if (attempt >= variants.length) return null;
  const v = variants[attempt];
  return {
    uri: v.url,
    ...(v.type ? {type: v.type} : {}),
    ...(isLive ? {headers: {'User-Agent': LIVE_UA}} : {}),
    ...extra,
  };
}

/** תיאור קצר של הניסיון, להודעת השגיאה. */
export function variantLabel(url, attempt) {
  const variants = streamVariants(url);
  const v = variants[attempt];
  if (!v) return '?';
  const kind = v.type === 'm3u8' ? 'HLS' : v.type ? v.type : 'ישיר';
  const same = v.url === String(url || '');
  return same ? kind : `${kind}+${v.url.slice(v.url.lastIndexOf('.'))}`;
}

export function variantCount(url) {
  return streamVariants(url).length;
}
