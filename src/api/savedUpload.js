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
import RNFS from 'react-native-fs';

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
 */
export function uploadToServer({code, uri, name, caption, onProgress}) {
  // binaryStreamOnly: הקובץ נשלח כגוף גולמי ולא כ-multipart. השרת אינו תומך
  // ב-multipart בכוונה (הוא היה דורש חבילה נוספת שאם היא חסרה השירות כולו
  // לא עולה), וגם ככה חוסכים קידוד ופענוח על קובץ של גיגה־בייטים.
  const q = `name=${encodeURIComponent(name || 'video.mp4')}` +
            `&caption=${encodeURIComponent(caption || '')}`;
  const {promise} = RNFS.uploadFiles({
    toUrl: `${BASE}/panel/saved-upload?${q}`,
    method: 'POST',
    binaryStreamOnly: true,
    headers: {'x-upload-code': code},
    files: [{name: 'file', filename: name || 'video.mp4', filepath: uri}],
    progress: r => {
      if (onProgress) onProgress(r.totalBytesSent, r.totalBytesExpectedToSend);
    },
  });
  return promise.then(r => {
    let body = {};
    try { body = JSON.parse(r.body); } catch { /* גוף שאינו JSON */ }
    if (r.statusCode !== 200) {
      throw new Error(body.detail || `השרת החזיר ${r.statusCode}`);
    }
    return body;              // {ok, job, size}
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
