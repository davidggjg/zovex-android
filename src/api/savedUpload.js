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
 * שלב ①: מעלה את הקובץ לשרת ומחזיר את מזהה המשימה.
 * onProgress מקבל (בייטים שנשלחו, סה"כ).
 *
 * הגוף נשלח גולמי, לא multipart: השרת אינו תומך ב-multipart בכוונה (הוא היה
 * דורש חבילה נוספת שאם היא חסרה השירות כולו לא עולה), וגם ככה חוסכים קידוד
 * ופענוח על קובץ של גיגה־בייטים.
 *
 * למה XMLHttpRequest ולא react-native-fs: `RNFS.uploadFiles` פותח את הקובץ
 * ב-`new File(filepath)`, כלומר נתיב מערכת קבצים בלבד. בורר הגלריה לעולם לא
 * מחזיר נתיב כזה — הוא מחזיר `content://…` (ולפעמים `file://…`), ושניהם
 * נכשלים שם ב-FileNotFoundException. RNFS מדווח על הכשל הזה עם ה-URL של
 * היעד במקום עם הנתיב, ומכאן הודעת ה-ENOENT המבלבלת שהצביעה על הכתובת.
 * ה-XHR של React Native, לעומת זאת, מקבל `{uri}` ופותח אותו דרך
 * ContentResolver — שיודע לטפל בשתי הסכימות — ומדווח התקדמות אמיתית.
 */
export function uploadToServer({code, uri, name, type, caption,
                                duration, width, height, onProgress}) {
  // אורך ומידות נשלחים לשרת כדי שיעביר אותם לטלגרם. בלעדיהם ההודעה בטלגרם
  // מציגה 0:00 ותצוגה מקדימה שחורה: טלגרם שומר בדיוק את מה שנמסר לו, ומי
  // ששולח וידאו בלי המטא־דאטה הזאת שולח אפסים. הקובץ עצמו תקין — רק
  // ההודעה משקרת, וכל דבר שיקרא את המטא־דאטה הזאת בהמשך יקבל אפס.
  const n = v => (Number.isFinite(v) && v > 0 ? Math.round(v) : 0);
  const q = `name=${encodeURIComponent(name || 'video.mp4')}` +
            `&caption=${encodeURIComponent(caption || '')}` +
            `&duration=${n(duration)}&width=${n(width)}&height=${n(height)}`;

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE}/panel/saved-upload?${q}`);
    // חובה: בלי Content-Type המודול הצדדי דוחה גוף מסוג uri על הסף.
    xhr.setRequestHeader('Content-Type', type || 'application/octet-stream');
    xhr.setRequestHeader('x-upload-code', code);
    xhr.timeout = 0;                       // קובץ גדול הוא לא תקלה

    if (onProgress && xhr.upload) {
      xhr.upload.onprogress = e => onProgress(e.loaded, e.total);
    }
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* גוף שאינו JSON */ }
      if (xhr.status !== 200) {
        reject(new Error(body.detail || `השרת החזיר ${xhr.status}`));
        return;
      }
      resolve(body);                       // {ok, job, size}
    };
    xhr.onerror = () => reject(new Error('אין חיבור לשרת'));
    xhr.onabort = () => reject(new Error('ההעלאה בוטלה'));
    xhr.ontimeout = () => reject(new Error('פג הזמן'));

    xhr.send({uri});
  });
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
