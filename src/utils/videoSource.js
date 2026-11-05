// ── מקור הווידאו של פריט, במקום אחד ─────────────────────────────────────────
//
// למה הקובץ הזה נולד: הנגן (PlayerScreen.buildSrc) ידע לנקות כתובות שבורות
// ולהמיר הפניית טלגרם לכתובת /stream אמיתית — ובדיקת ההורדה
// (isItemDownloadable) קראה את השדה הגולמי מהקטלוג. התוצאה הייתה שבתוך
// אותה סדרה לחלק מהפרקים היה כפתור הורדה ולחלק לא, בלי שום הבדל אמיתי
// ביניהם: אותו פרק בדיוק התנגן מצוין והכפתור פשוט לא הופיע.
//
// עכשיו שני המסלולים קוראים מכאן.

export const TG_PROXY = 'https://zovex.duckdns.org';

// שמות ערוצים → מזהים מספריים (זהה ל-CustomVideoPlayer.jsx).
export const TG_CHANNELS = {zove8: '7282626428', ZOVE8: '7282626428'};

// שתי צורות שבורות שקיימות בקטלוג בפועל, ושתיהן ניתנות לשחזור ודאי:
//
//   <iframe src="https://…"></iframe>   הודבק קוד ההטמעה במקום הכתובת.
//                                       ב"פאוור קאפל" 7 פרקים שמורים כתובת
//                                       נקייה ו-3 כ-iframe שלם — אותו יעד
//                                       בדיוק, ולכן החילוץ אינו ניחוש.
//   ttps://…                            נבלעה ה-h הראשונה. ב"הכבוד של אשרף"
//                                       9 פרקים כאלה; הם ניצלו במקרה כי זיהוי
//                                       dailymotion מסתכל על הדומיין ולא על
//                                       הסכימה, אבל אותה תקלה בכתובת ישירה
//                                       שוברת אותה לגמרי.
//
// מנקים בכניסה, כדי שכל ענפי הזיהוי יקבלו כתובת אמיתית.
export function cleanVideoRef(raw) {
  let v = (raw || '').trim();
  if (!v) return '';
  const iframe = v.match(/<iframe[^>]*\ssrc=["']([^"']+)["']/i);
  if (iframe) v = iframe[1].trim();
  v = v.replace(/^(?:ttps?):\/\//i, m => (m.toLowerCase().startsWith('ttps') ? 'https://' : 'http://'));
  return v.replace(/&amp;/g, '&');
}

// הפניית טלגרם → כתובת /stream מהשרת שלנו, שהיא קובץ רגיל לכל דבר.
// מחזיר null כשההפניה לא ניתנת לפתרון (ערוץ לא מוכר ולא מספרי) — ואז
// הנגן נופל להטמעת t.me, שאיננה קובץ ולכן גם לא ניתנת להורדה.
export function telegramStreamUrl(vid) {
  const v = (vid || '').trim();
  if (!v) return null;
  // כבר כתובת ישירה (למשל /stream שנשמר בקטלוג כמו שהוא).
  if (v.startsWith('http') && !v.includes('t.me')) return v;
  const tgId = v.replace(/^https?:\/\/t\.me\//, '');
  const parts = tgId.split('/').filter(Boolean);
  const chanRaw = parts[0] || '';
  const msgId = parts[parts.length - 1];
  if (!msgId) return null;
  if (/^\d+$/.test(chanRaw)) return `${TG_PROXY}/stream/${chanRaw}/${msgId}`;
  const numericId = TG_CHANNELS[chanRaw] || TG_CHANNELS[chanRaw.toLowerCase()];
  if (numericId) return `${TG_PROXY}/stream/${numericId}/${msgId}`;
  return null;
}

// ספקי הטמעה: הנגן פותח אותם ב-iframe, ולכן אין מהם קובץ לשמור. זו
// רשימה של מה שבאמת אי אפשר להוריד, להבדיל ממה שפשוט לא נבדק נכון.
const EMBED_TYPES = [
  'youtube', 'drive', 'vimeo', 'dailymotion', 'streamable',
  'rumble', 'archive', 'kan', 'okru', 'kaltura', 'jellyfin',
];
const EMBED_DOMAINS = [
  'youtube.com', 'youtu.be', 'drive.google.com', 'vimeo.com', 'dailymotion.com',
  'streamable.com', 'rumble.com', 'archive.org', 'kan.org.il', 'ok.ru', 'kaltura.com',
];

/**
 * הכתובת שממנה אפשר **לשמור קובץ** של הפריט, או null אם אין כזו.
 *
 * זו הפונקציה היחידה שמחליטה אם יש כפתור הורדה, והיא גם זו שבונה את
 * הכתובת שמורידים ממנה בפועל — כדי שלא ייתכן מצב שהכפתור מוצג וההורדה
 * מנסה כתובת אחרת.
 */
export function downloadableUrl(item) {
  if (!item || item.is_live) return null;
  const type = item.type;
  const vid = cleanVideoRef(item.video_id || item.video_url || '');
  if (!vid) return null;

  if (EMBED_TYPES.includes(type)) return null;
  if (EMBED_DOMAINS.some(d => vid.includes(d))) return null;

  // טלגרם הוא המקור של כל הקטלוג כאן, והשרת מגיש אותו כקובץ ב-/stream.
  // קודם הוא היה ברשימת החסומים יחד עם היוטיוב והדרייב, ולכן כפתור
  // ההורדה נעלם כמעט מכל פרק באפליקציה.
  if (type === 'telegram' || vid.includes('t.me')) return telegramStreamUrl(vid);

  return vid.startsWith('http') ? vid : null;
}
