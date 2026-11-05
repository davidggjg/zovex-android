import RNFS from 'react-native-fs';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {NativeModules} from 'react-native';

import {downloadableUrl} from '../utils/videoSource';

const {SecureDownload} = NativeModules;

// ── Offline downloads ────────────────────────────────────────────────────────
//
// שתי הגרסאות הקודמות לא הגנו על כלום:
//
//   1. XOR בייט-בייט ב-JavaScript עם מפתח ששכב על אותו מכשיר. ההערה בקוד
//      הודתה בעצמה ש"זו הרתעה, לא DRM אמיתי". בנוסף הוא רץ בלולאה פר-בייט
//      עם base64 הלוך ושוב: ~30 דקות להצפין קובץ של 1GB, ועוד ~30 לפענח
//      לפני שאפשר היה בכלל ללחוץ הפעל.
//   2. אחרי שהוסר: הקובץ נשמר **גלוי**. על מכשיר לא-רוּט אף אפליקציה אחרת
//      לא קוראת את התיקייה הפרטית, אבל מכשיר מרוּט, גיבוי, או הוצאה של
//      האפליקציה מהמכשיר — ומקבלים MP4 שלם ונקי.
//
// עכשיו ההצפנה היא נייטיב, עם מפתח שנעול בחומרה של המכשיר: מפתח-על
// AES-256 שנוצר **בתוך** StrongBox/TEE ואין API שמוציא אותו (גם לא ל-root),
// ומעליו מפתח נתונים אקראי לכל הורדה שנעטף בו ונשמר בכותרת הקובץ.
// גוף הווידאו הוא AES-256-CTR. ראה
// android/app/src/main/java/com/zovexapp/SecureDownloadModule.kt לפרטים,
// ו-docs/offline-drm.md למה שחסר כדי להגיע ל-Widevine אמיתי.
//
// הניגון: אין רגע שבו קובץ מפוענח יושב על הדיסק. הפענוח זורם מול שרת
// שמאזין רק על 127.0.0.1, מול אסימון אקראי חד-פעמי לאותה צפייה.

const MANIFEST_KEY = 'zovex_downloads_manifest_v1';
const DL_DIR = RNFS.DocumentDirectoryPath + '/zvxdl';
// ‎.zvx‎ ולא ‎.mp4‎: הקובץ איננו MP4 — הוא כותרת ואחריה טקסט מוצפן. סיומת
// שמשקרת רק גורמת לנגנים חיצוניים לנסות לפתוח אותו ולהיכשל.
const encPathFor = id => `${DL_DIR}/${id}.zvx`;

async function ensureDirs() {
  if (!(await RNFS.exists(DL_DIR))) await RNFS.mkdir(DL_DIR);
}

async function loadManifest() {
  const raw = await AsyncStorage.getItem(MANIFEST_KEY);
  try {
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

async function saveManifest(list) {
  await AsyncStorage.setItem(MANIFEST_KEY, JSON.stringify(list));
}

// נתיב הקובץ המקומי של פריט, לכל דור של כניסות — ‎encPath‎ (XOR הישן),
// ‎filePath‎ (התקופה שבה הקובץ נשמר גלוי) ו-‎securePath‎ (היום). משמש
// למחיקה, שחייבת לעבוד על כל אחד מהם.
function entryPath(entry) {
  return entry.securePath || entry.filePath || entry.encPath || null;
}

// רק כניסה מוצפנת נחשבת זמינה לניגון. כניסה מדור קודם תיראה כלא-מורדת
// ותורד מחדש — זה בדיוק מה שצריך לקרות: אין לנו דרך לנגן XOR ישן, ואין
// שום סיבה להמשיך להחזיק קובץ גלוי על המכשיר.
const isPlayable = m => !!(m && m.securePath);

export async function getDownloads() {
  return loadManifest();
}

// ── ניקוי הורדות מדורות קודמים ───────────────────────────────────────────
// כניסות ישנות מצביעות על קובץ XOR (encPath) או על וידאו גלוי (filePath).
// אי אפשר לנגן אף אחד מהם במסלול החדש, ואין שום סיבה להשאיר וידאו גלוי
// על המכשיר אחרי שהוספנו הצפנה — זו בדיוק הבעיה שתוקנה. מוחקים ומסירים
// מהרשימה; הפריט פשוט יוצג כלא-מורד וניתן להורדה מחדש.
//
// נקרא פעם אחת בעליית האפליקציה. בטוח להיקרא שוב: אין מה למחוק בפעם השנייה.
export async function purgeLegacyDownloads() {
  const manifest = await loadManifest();
  const legacy = manifest.filter(m => !isPlayable(m));
  if (!legacy.length) return 0;
  for (const entry of legacy) {
    for (const f of [entry.filePath, entry.encPath, entry.posterLocalPath]) {
      try { if (f && (await RNFS.exists(f))) await RNFS.unlink(f); } catch (_) {}
    }
  }
  await saveManifest(manifest.filter(isPlayable));
  return legacy.length;
}

export async function isDownloaded(id) {
  const list = await loadManifest();
  return list.some(m => m.id === String(id) && isPlayable(m));
}

export async function getDownloadedIds() {
  const list = await loadManifest();
  return new Set(list.filter(isPlayable).map(m => m.id));
}

// ניתן להורדה רק כשיש כתובת שממנה אפשר לשמור קובץ. ההחלטה עצמה חיה
// ב-src/utils/videoSource.js, יחד עם בניית הכתובת שמורידים ממנה בפועל.
//
// שתי תקלות שהיו כאן, ושתיהן נראו למשתמש אותו דבר — "לחלק מהפרקים בסדרה
// יש כפתור הורדה ולחלק אין, בלי שום היגיון":
//
//   • טלגרם היה ברשימת החסומים יחד עם יוטיוב ודרייב. אבל כל הקטלוג כאן
//     מגיע מטלגרם דרך השרת, שמגיש אותו כקובץ ב-/stream — כלומר הוא
//     הדבר הכי ניתן להורדה שיש, והכפתור נעלם כמעט מכל פרק.
//   • הבדיקה קראה את השדה הגולמי מהקטלוג, בלי cleanVideoRef. פרקים
//     ששמורים כ-‎ttps://…‎ (נבלעה ה-h) או כקוד ‎<iframe>‎ שלם נפלו על
//     ‎startsWith('http')‎ — ולכן אותו פרק בדיוק התנגן מצוין ולא היה
//     אפשר להוריד אותו.
export function isItemDownloadable(item) {
  return !!downloadableUrl(item);
}

export async function downloadItem(item, onProgress) {
  await ensureDirs();
  const id = String(item.id);
  // אותה כתובת בדיוק שהכפתור נשען עליה. קודם כאן נקרא השדה הגולמי, ולכן
  // פריט טלגרם היה מנסה להוריד ‎t.me/…‎ — דף HTML, לא וידאו.
  const videoUrl = downloadableUrl(item);
  if (!videoUrl) throw new Error('אין קישור וידאו ישיר להורדה');

  if (!SecureDownload) {
    // בלי המודול הנייטיב אין הצפנה, ושמירת וידאו גלוי על המכשיר היא בדיוק
    // מה שתוקן כאן. עדיף להיכשל ולהגיד למה מאשר "להצליח" בלי הגנה.
    throw new Error('רכיב ההצפנה אינו זמין בגרסה הזו — עדכן את האפליקציה');
  }

  const securePath = encPathFor(id);
  const partPath = `${DL_DIR}/${id}.part`;
  const posterPath = item.thumbnail_url ? `${DL_DIR}/${id}.poster.jpg` : null;

  if (await RNFS.exists(partPath)) await RNFS.unlink(partPath);
  if (await RNFS.exists(securePath)) await RNFS.unlink(securePath);

  // מהירות וזמן-שנותר על חלון גולל של ~5 שניות. ממוצע מתחילת ההורדה נועל
  // נמוך אחרי קטע איטי ולא זז; חלון קצר מתקן את עצמו מיד.
  const samples = [];
  const WINDOW_MS = 5000;
  let lastEmit = 0;

  function emit(bytesWritten, contentLength) {
    const now = Date.now();
    samples.push([now, bytesWritten]);
    while (samples.length > 2 && now - samples[0][0] > WINDOW_MS) samples.shift();
    let speed = 0; // bytes/sec
    if (samples.length >= 2) {
      const [t0, b0] = samples[0];
      const dt = (now - t0) / 1000;
      if (dt > 0) speed = (bytesWritten - b0) / dt;
    }
    const left = contentLength > 0 ? Math.max(0, contentLength - bytesWritten) : 0;
    const eta = speed > 0 && contentLength > 0 ? Math.round(left / speed) : null;
    onProgress?.({
      phase: 'downloading',
      pct: contentLength > 0 ? bytesWritten / contentLength : 0,
      bytesWritten,
      contentLength,
      speed,          // בייט לשנייה, על חלון של 5 שניות
      eta,            // שניות שנותרו, או null אם עוד לא ידוע
    });
  }

  const dl = RNFS.downloadFile({
    fromUrl: videoUrl,
    toFile: partPath,
    // progressDivider:0 → דיווח על כל טיק, כדי שספירת ה-MB תזוז תוך שנייה
    // גם כשהאחוז כמעט לא זז (קבצים גדולים על קו איטי).
    progressDivider: 0,
    begin: res => {
      if (res.contentLength > 0) emit(0, res.contentLength);
    },
    progress: res => {
      const now = Date.now();
      if (now - lastEmit < 250) return;   // מגבילים ~4 עדכונים לשנייה
      lastEmit = now;
      emit(res.bytesWritten, res.contentLength);
    },
  });
  const result = await dl.promise;
  if (result.statusCode && result.statusCode >= 400) {
    if (await RNFS.exists(partPath)) await RNFS.unlink(partPath);
    throw new Error(`ההורדה נכשלה (${result.statusCode})`);
  }

  // הקובץ ירד במלואו. עכשיו מצפינים אותו לשם הסופי — והנייטיב מוחק את
  // ה-.part הגולמי ברגע שהיעד נכתב במלואו, כך שאין חלון שבו וידאו גלוי
  // שוכב על המכשיר אחרי שההורדה נגמרה. עד לרגע הזה אין קובץ "מוכן",
  // ולכן הורדה שנקטעה לא נחשבת בטעות כזמינה.
  //
  // זה AES-256 בקוד נייטיב ולא לולאת XOR ב-JS: מדובר בשניות, לא בחצי
  // שעה שהגרסה הישנה לקחה על קובץ של 1GB.
  onProgress?.({phase: 'encrypting', pct: 1});
  await SecureDownload.encryptFile(partPath, securePath);

  if (posterPath) {
    try {
      if (await RNFS.exists(posterPath)) await RNFS.unlink(posterPath);
      await RNFS.downloadFile({fromUrl: item.thumbnail_url, toFile: posterPath}).promise;
    } catch {
      // poster is a nice-to-have for offline browsing; not fatal
    }
  }

  const stat = await RNFS.stat(securePath);
  const entry = {
    id,
    title: item.title || item.name || '',
    seriesName: item.series_name || null,
    seasonNumber: item.season_number || null,
    episodeNumber: item.episode_number || null,
    episodeTitle: item.episode_title || null,
    posterLocalPath: posterPath && (await RNFS.exists(posterPath)) ? posterPath : null,
    securePath,
    sizeBytes: parseInt(stat.size, 10),
    downloadedAt: new Date().toISOString(),
  };

  const manifest = (await loadManifest()).filter(m => m.id !== id);
  manifest.push(entry);
  await saveManifest(manifest);
  return entry;
}

export async function deleteDownload(id) {
  const strId = String(id);
  const manifest = await loadManifest();
  const entry = manifest.find(m => m.id === strId);
  if (entry) {
    const p = entryPath(entry);
    if (p && (await RNFS.exists(p))) await RNFS.unlink(p);
    if (entry.posterLocalPath && (await RNFS.exists(entry.posterLocalPath))) {
      await RNFS.unlink(entry.posterLocalPath);
    }
  }
  await saveManifest(manifest.filter(m => m.id !== strId));
}

// הפענוח קורה בזרם, ולא לקובץ זמני: אין שום רגע שבו וידאו גלוי יושב על
// הדיסק — גם לא באמצע צפייה. מחזירים כתובת של שרת שמאזין רק על 127.0.0.1,
// מול אסימון אקראי שנוצר עכשיו ומת ב-cleanup (שה-PlayerScreen קורא לו
// כשיוצאים מהנגן, דרך onLeaveCleanup).
//
// הניגון מיידי: אין יותר שלב פענוח מקדים. הגרסה עם ה-XOR פענחה קובץ שלם
// לפני שהיה אפשר ללחוץ הפעל — כ-30 דקות על קובץ של 1GB.
export async function preparePlayback(id) {
  const strId = String(id);
  const manifest = await loadManifest();
  const entry = manifest.find(m => m.id === strId);
  const p = entry && entry.securePath;
  if (!p || !(await RNFS.exists(p))) {
    throw new Error('קובץ ההורדה לא נמצא — ייתכן שההורדה לא הסתיימה. הורד שוב.');
  }
  if (!SecureDownload) {
    throw new Error('רכיב ההצפנה אינו זמין בגרסה הזו — עדכן את האפליקציה');
  }
  const {url, token} = await SecureDownload.serve(p);
  return {
    uri: url,
    cleanup: () => { try { SecureDownload.stopServing(token); } catch (_) {} },
  };
}

// Shapes a manifest entry like a regular catalog item so it can flow through
// the same MovieCard / MovieDetailModal components used for remote content.
export function downloadEntryToMovie(entry) {
  return {
    id: entry.id,
    title: entry.title,
    name: entry.title,
    series_name: entry.seriesName || undefined,
    season_number: entry.seasonNumber || undefined,
    episode_number: entry.episodeNumber || undefined,
    episode_title: entry.episodeTitle || undefined,
    thumbnail_url: entry.posterLocalPath ? 'file://' + entry.posterLocalPath : undefined,
    description: '',
    type: 'direct',
    __isDownload: true,
    __downloadId: entry.id,
  };
}
