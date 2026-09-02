// ─────────────────────────────────────────────────────────────────────────────
// העלאת וידאו מהגלריה אל "הודעות שמורות" בטלגרם, דרך השרת.
//
//   טלפון ──①──▶ שרת (קובץ זמני) ──②──▶ יוזרבוט ──▶ הודעות שמורות
//                      └────────③ מחיקה ─────────┘
//
// שני שלבים, ולכן שני מדדי התקדמות: ① נמדד כאן במכשיר, ② נמדד בשרת ונשאב
// בתשאול. אין דרך לאחד אותם — אלה שתי העברות רשת נפרדות.
//
// קוד הכניסה אינו שמור כאן. APK הוא ZIP, ו-`strings` מוציא ממנו כל מחרוזת
// בשניות; קוד שיושב באפליקציה שקול לקוד פומבי. מה שהוקלד נשלח לשרת לאימות,
// והשרת הוא זה שמחזיק את הסוד — כך גם אפשר להחליף אותו בלי לבנות APK חדש.
// ─────────────────────────────────────────────────────────────────────────────
import {NativeModules, DeviceEventEmitter} from 'react-native';

const {ZovexUploader} = NativeModules;
const BASE = 'https://zovex.duckdns.org';

/** בודק קוד מול השרת. מחזיר {ok, account, ready} או זורק שגיאה מוסברת. */
export async function verifyPanelCode(code) {
  const res = await fetch(`${BASE}/panel/entry-code`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({code}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `שגיאה ${res.status}`);
  return data;
}

/**
 * שלב ①: מעלה את הקובץ לשרת. ההעלאה עצמה רצה בצד הנייטיבי.
 *
 * הגוף נשלח גולמי, לא multipart: השרת אינו תומך ב-multipart בכוונה (הוא היה
 * דורש חבילה נוספת שאם היא חסרה השירות כולו לא עולה), וגם ככה חוסכים קידוד
 * ופענוח על קובץ של גיגה־בייטים.
 *
 * למה נייטיבי ולא ה-XHR של React Native, שהיה כאן קודם: RN קובע את אורך הגוף
 * לפי `inputStream.available()`, שמחזיר int — תקרה של 2GB. הזרם עצמו מחמיר,
 * כי הבנאי של AssetFileDescriptor.AutoCloseInputStream ב-AOSP כותב
 * `mRemaining = (int)fd.getLength()`, כלומר חותך long ל-int. קובץ של 3.34GB
 * הצהיר על אורך שגוי, החיבור נשבר, וכל מה שהגיע לכאן היה "כשל רשת".
 * הצד הנייטיבי לוקח את הגודל מ-ContentResolver כ-long ומוסר אותו ל-
 * setFixedLengthStreamingMode(long), ולכן גודל הקובץ אינו מגביל אותו.
 *
 * הוא גם רץ לצד שירות חזית, כך שיציאה מהאפליקציה אינה קוטעת את ההעלאה.
 * ההתקדמות מגיעה באירועים ולא ב-callback, כי ההעלאה שורדת גם מסך שנסגר.
 */
export function startUpload({code, uri, name, type, size, caption,
                             duration, width, height}) {
  if (!ZovexUploader) {
    return Promise.reject(new Error('מנגנון ההעלאה אינו זמין בגרסה הזאת'));
  }
  // אורך ומידות נשלחים לשרת כדי שיעביר אותם לטלגרם. בלעדיהם ההודעה בטלגרם
  // מציגה 0:00 ותצוגה מקדימה שחורה: טלגרם שומר בדיוק את מה שנמסר לו, ומי
  // ששולח וידאו בלי המטא־דאטה הזאת שולח אפסים. הקובץ עצמו תקין — רק
  // ההודעה משקרת, וכל דבר שיקרא את המטא־דאטה הזאת בהמשך יקבל אפס.
  const n = v => (Number.isFinite(v) && v > 0 ? Math.round(v) : 0);
  const q = `name=${encodeURIComponent(name || 'video.mp4')}` +
            `&caption=${encodeURIComponent(caption || '')}` +
            `&duration=${n(duration)}&width=${n(width)}&height=${n(height)}`;

  return ZovexUploader.start({
    uri,
    url: `${BASE}/panel/saved-upload?${q}`,
    code: code || '',
    // חובה: בלי Content-Type השרת אינו יודע לזהות את הגוף.
    type: type || 'application/octet-stream',
    name: name || 'video.mp4',
    size: size || 0,
  });
}

/** מנוי לאירועי ההעלאה: {type: progress|done|error, sent, total, job, error}. */
export function onUpload(handler) {
  return DeviceEventEmitter.addListener('zovexUpload', handler);
}

/** מצב ההעלאה כרגע — כדי שמסך שנפתח מחדש יתחבר להעלאה שכבר רצה. */
export function getUploadState() {
  return ZovexUploader ? ZovexUploader.getState() : Promise.resolve(null);
}

export function cancelUpload() {
  return ZovexUploader ? ZovexUploader.cancel() : Promise.resolve(false);
}

/** שלב ②: מצב ההעלאה מהשרת לטלגרם. */
export async function fetchJobStatus(job) {
  const res = await fetch(
    `${BASE}/panel/saved-upload/status?job=${encodeURIComponent(job)}`);
  if (!res.ok) throw new Error(`שגיאה ${res.status}`);
  return res.json();
}

export function fmtBytes(n) {
  if (!n && n !== 0) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1073741824) return `${(n / 1048576).toFixed(1)} MB`;
  return `${(n / 1073741824).toFixed(2)} GB`;
}

export function fmtEta(sec) {
  if (sec == null || !isFinite(sec) || sec < 0) return '—';
  if (sec < 60) return `${Math.round(sec)} שנ׳`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m} דק׳ ${Math.round(sec % 60)} שנ׳`;
  return `${Math.floor(m / 60)} שע׳ ${m % 60} דק׳`;
}
