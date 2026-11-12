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
 * רשימת הדרכים לנסות לנגן את הכתובת, לפי סדר. כל איבר הוא ה-source
 * של react-native-video, בלי ה-uri (הנגן מוסיף אותו).
 *
 * ‎{}‎ פירושו "בלי type" — ExoPlayer בונה ProgressiveMediaSource ומריץ
 * את ה-extractors שלו, שכוללים את TsExtractor. זה המסלול שמנגן
 * MPEG-TS גולמי, וזה בדיוק מה שהיה חסר.
 */
export function streamVariants(url) {
  const u = String(url || '');
  const {last} = lastSegment(u);

  if (/\.m3u8?(?:$|[?#])/i.test(u)) return [{type: 'm3u8'}, {}];
  if (/\.mpd(?:$|[?#])/i.test(u)) return [{type: 'mpd'}];
  if (/\.ism|Manifest\.ism/i.test(u)) return [{type: 'ism'}, {type: 'm3u8'}];
  // מיכלים ישירים: קודם progressive, ו-HLS רק כגיבוי — יש שרתים
  // שמגישים פלייליסט מכתובת שנגמרת ב-.ts.
  if (/\.(?:ts|mpeg|mpg|mkv|avi|webm)(?:$|[?#])/i.test(u)) return [{}, {type: 'm3u8'}];
  if (/\.(?:mp4|m4v|mov)(?:$|[?#])/i.test(u)) return [{type: 'mp4'}, {}];

  // בלי סיומת. צורת Xtream → כמעט תמיד TS גולמי, ולכן progressive ראשון.
  if (isXtreamStyle(u)) return [{}, {type: 'm3u8'}];

  // כל השאר בלי סיומת: נשאר כמו שהיה — HLS ראשון — כדי לא לשבור ערוצים
  // שכבר עובדים; אבל עכשיו יש גם ניסיון שני במקום להיכשל.
  if (!hasExt(last)) return [{type: 'm3u8'}, {}];

  return [{}, {type: 'm3u8'}];
}

/**
 * ה-source המלא לניסיון מספר [attempt]. מעבר לסוף הרשימה מוחזר null,
 * כדי שהנגן יידע שנגמרו הדרכים ויעבור לנגן הבא בשרשרת במקום להסתובב.
 */
export function buildStreamSource(url, attempt = 0, {isLive = false, extra = {}} = {}) {
  const variants = streamVariants(url);
  if (attempt >= variants.length) return null;
  return {
    uri: String(url || ''),
    ...variants[attempt],
    ...(isLive ? {headers: {'User-Agent': LIVE_UA}} : {}),
    ...extra,
  };
}

export function variantCount(url) {
  return streamVariants(url).length;
}
