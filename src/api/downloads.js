import RNFS from 'react-native-fs';
import AsyncStorage from '@react-native-async-storage/async-storage';

// ── Offline downloads ────────────────────────────────────────────────────────
// Downloaded videos are stored *as-is* under an obscure filename in the app's
// private document directory - a location no other app (gallery, file manager,
// etc.) can read on a non-rooted device, the same way Netflix and other
// streaming apps keep offline downloads out of reach.
//
// Previous versions XOR-encrypted every file with an on-device key. The code's
// own comment admitted it was "a deterrent, not real DRM - anyone who
// reverse-engineers the app could recover the key." It added no real security
// against that threat (the key sits on the same device), but it cost a fortune:
// the XOR ran in pure JS with base64 round-trips and a per-byte loop, reading
// and rewriting the whole file in 3MB chunks. On a 1GB file that was ~30
// minutes to "encrypt" after the download, and ANOTHER ~30 minutes to decrypt
// before playback could even start - which looked exactly like "offline
// playback doesn't work." Dropping it makes finishing a download and starting
// playback instant, while the private-storage hiding (the actual protection)
// stays. If real DRM is ever needed it must be native (Widevine), never JS XOR.

const MANIFEST_KEY = 'zovex_downloads_manifest_v1';
// שם מוסתר; רק סיומת וידאו כדי שהנגן/ExoPlayer יזהה מיכל. נשאר באחסון הפרטי.
const DL_DIR = RNFS.DocumentDirectoryPath + '/zvxdl';

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

// נתיב הקובץ המקומי של פריט. תומך גם בכניסות ישנות (encPath) לצורך מחיקה,
// אבל כניסות ישנות היו מוצפנות ולא ינוגנו — הן פשוט יורדו מחדש.
function entryPath(entry) {
  return entry.filePath || entry.encPath || null;
}

export async function getDownloads() {
  return loadManifest();
}

export async function isDownloaded(id) {
  const list = await loadManifest();
  return list.some(m => m.id === String(id) && m.filePath);
}

export async function getDownloadedIds() {
  const list = await loadManifest();
  return new Set(list.filter(m => m.filePath).map(m => m.id));
}

// Downloadable only if we have a direct playable file URL (not an iframe
// embed like YouTube/Vimeo/Drive/Kaltura - those can't be saved as a file).
export function isItemDownloadable(item) {
  if (!item || item.is_live) return false;
  const vid = (item.video_id || item.video_url || '').trim();
  if (!vid.startsWith('http')) return false;
  const nonDownloadableTypes = [
    'youtube', 'drive', 'vimeo', 'dailymotion', 'streamable', 'rumble',
    'archive', 'kan', 'okru', 'kaltura', 'jellyfin', 'telegram',
  ];
  if (nonDownloadableTypes.includes(item.type)) return false;
  if (vid.includes('kaltura.com') || vid.includes('youtube.com') || vid.includes('youtu.be') ||
      vid.includes('drive.google.com') || vid.includes('vimeo.com') || vid.includes('dailymotion.com') ||
      vid.includes('t.me')) return false;
  return true;
}

export async function downloadItem(item, onProgress) {
  await ensureDirs();
  const id = String(item.id);
  const videoUrl = (item.video_url || item.video_id || '').trim();
  if (!videoUrl.startsWith('http')) throw new Error('אין קישור וידאו ישיר להורדה');

  const filePath = `${DL_DIR}/${id}.mp4`;
  const partPath = `${DL_DIR}/${id}.part`;
  const posterPath = item.thumbnail_url ? `${DL_DIR}/${id}.poster.jpg` : null;

  if (await RNFS.exists(partPath)) await RNFS.unlink(partPath);
  if (await RNFS.exists(filePath)) await RNFS.unlink(filePath);

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

  // הקובץ ירד במלואו — מעבירים ממנת ה-.part לשם הסופי. עד לרגע הזה אין קובץ
  // "מוכן", כך שהורדה שנקטעה לא נחשבת בטעות כזמינה.
  await RNFS.moveFile(partPath, filePath);

  if (posterPath) {
    try {
      if (await RNFS.exists(posterPath)) await RNFS.unlink(posterPath);
      await RNFS.downloadFile({fromUrl: item.thumbnail_url, toFile: posterPath}).promise;
    } catch {
      // poster is a nice-to-have for offline browsing; not fatal
    }
  }

  const stat = await RNFS.stat(filePath);
  const entry = {
    id,
    title: item.title || item.name || '',
    seriesName: item.series_name || null,
    seasonNumber: item.season_number || null,
    episodeNumber: item.episode_number || null,
    episodeTitle: item.episode_title || null,
    posterLocalPath: posterPath && (await RNFS.exists(posterPath)) ? posterPath : null,
    filePath,
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

// אין יותר פענוח: הקובץ שמור כמו שהוא, ומחזירים לו file:// ישירות. הניגון
// מיידי. cleanup הוא no-op — אין קובץ זמני למחוק (הקובץ הקבוע נשאר).
export async function preparePlayback(id) {
  const strId = String(id);
  const manifest = await loadManifest();
  const entry = manifest.find(m => m.id === strId);
  const p = entry && entry.filePath;
  if (!p || !(await RNFS.exists(p))) {
    throw new Error('קובץ ההורדה לא נמצא — ייתכן שההורדה לא הסתיימה. הורד שוב.');
  }
  return {
    uri: 'file://' + p,
    cleanup: () => {},
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
