import RNFS from 'react-native-fs';
import AsyncStorage from '@react-native-async-storage/async-storage';
import base64js from 'base64-js';

// ── Offline downloads ────────────────────────────────────────────────────────
// Downloaded videos are stored encrypted (XOR stream cipher, keyed by a
// per-install random key that never leaves the device) under an obscure
// filename in the app's *private* document directory - a location no other
// app (gallery, file manager, etc.) can read on modern Android without root,
// same as how Netflix/other streaming apps keep offline downloads out of
// reach. This is a deterrent, not real DRM: anyone who fully reverse-engineers
// the app could recover the key. It stops casual extraction/sharing, which is
// the actual goal here - it isn't Widevine.

const MANIFEST_KEY = 'zovex_downloads_manifest_v1';
const CIPHER_KEY_STORAGE = 'zovex_downloads_cipher_key_v1';
const CHUNK_BYTES = 3 * 1024 * 1024; // 3MB per read/write chunk

const DL_DIR = RNFS.DocumentDirectoryPath + '/zvxdl';
const TMP_PLAY_DIR = RNFS.CachesDirectoryPath + '/zvxplay';

async function ensureDirs() {
  if (!(await RNFS.exists(DL_DIR))) await RNFS.mkdir(DL_DIR);
  if (!(await RNFS.exists(TMP_PLAY_DIR))) await RNFS.mkdir(TMP_PLAY_DIR);
}

function generateKeyBytes(len = 32) {
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = Math.floor(Math.random() * 256);
  return bytes;
}

async function getOrCreateCipherKey() {
  const stored = await AsyncStorage.getItem(CIPHER_KEY_STORAGE);
  if (stored) return base64js.toByteArray(stored);
  const bytes = generateKeyBytes(32);
  await AsyncStorage.setItem(CIPHER_KEY_STORAGE, base64js.fromByteArray(bytes));
  return bytes;
}

// Symmetric: calling this twice with the same key encrypts, then decrypts.
async function xorTransformFile(srcPath, destPath, keyBytes, onProgress) {
  const stat = await RNFS.stat(srcPath);
  const total = parseInt(stat.size, 10);
  if (await RNFS.exists(destPath)) await RNFS.unlink(destPath);
  let offset = 0;
  while (offset < total) {
    const len = Math.min(CHUNK_BYTES, total - offset);
    const b64 = await RNFS.read(srcPath, len, offset, 'base64');
    const bytes = base64js.toByteArray(b64);
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = bytes[i] ^ keyBytes[(offset + i) % keyBytes.length];
    }
    await RNFS.appendFile(destPath, base64js.fromByteArray(bytes), 'base64');
    offset += len;
    onProgress?.(total > 0 ? offset / total : 1);
  }
  return total;
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

export async function getDownloads() {
  return loadManifest();
}

export async function isDownloaded(id) {
  const list = await loadManifest();
  return list.some(m => m.id === String(id));
}

export async function getDownloadedIds() {
  const list = await loadManifest();
  return new Set(list.map(m => m.id));
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

  const key = await getOrCreateCipherKey();
  const rawTmpPath = `${TMP_PLAY_DIR}/${id}.raw.tmp`;
  const encPath = `${DL_DIR}/${id}.zvx`;
  const posterPath = item.thumbnail_url ? `${DL_DIR}/${id}.poster.jpg` : null;

  if (await RNFS.exists(rawTmpPath)) await RNFS.unlink(rawTmpPath);
  if (await RNFS.exists(encPath)) await RNFS.unlink(encPath);

  try {
    // Content is proxied through a slow, bandwidth-constrained backend and
    // files often run 1GB+, so a download can sit at the same percentage for
    // 15-20s at a time. progressDivider:2 (native reports only every whole
    // 2% of progress) made that far worse - combined with the file size it
    // could look completely frozen for the first 20-30s. Report on every
    // native tick instead (progressDivider:0) and pass along raw byte counts
    // so the UI can show live MB progress, which moves within a second or
    // two even while the percentage itself barely ticks.
    let lastEmit = 0;
    const dl = RNFS.downloadFile({
      fromUrl: videoUrl,
      toFile: rawTmpPath,
      progressDivider: 0,
      begin: res => {
        if (res.contentLength > 0) {
          onProgress?.({phase: 'downloading', pct: 0, bytesWritten: 0, contentLength: res.contentLength});
        }
      },
      progress: res => {
        if (res.contentLength > 0) {
          const now = Date.now();
          if (now - lastEmit < 250) return;
          lastEmit = now;
          onProgress?.({
            phase: 'downloading',
            pct: res.bytesWritten / res.contentLength,
            bytesWritten: res.bytesWritten,
            contentLength: res.contentLength,
          });
        }
      },
    });
    await dl.promise;

    await xorTransformFile(rawTmpPath, encPath, key, pct =>
      onProgress?.({phase: 'encrypting', pct}),
    );
  } finally {
    if (await RNFS.exists(rawTmpPath)) await RNFS.unlink(rawTmpPath);
  }

  if (posterPath) {
    try {
      await RNFS.downloadFile({fromUrl: item.thumbnail_url, toFile: posterPath}).promise;
    } catch {
      // poster is a nice-to-have for offline browsing; not fatal
    }
  }

  const stat = await RNFS.stat(encPath);
  const entry = {
    id,
    title: item.title || item.name || '',
    seriesName: item.series_name || null,
    seasonNumber: item.season_number || null,
    episodeNumber: item.episode_number || null,
    episodeTitle: item.episode_title || null,
    posterLocalPath: posterPath && (await RNFS.exists(posterPath)) ? posterPath : null,
    encPath,
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
    if (await RNFS.exists(entry.encPath)) await RNFS.unlink(entry.encPath);
    if (entry.posterLocalPath && (await RNFS.exists(entry.posterLocalPath))) {
      await RNFS.unlink(entry.posterLocalPath);
    }
  }
  await saveManifest(manifest.filter(m => m.id !== strId));
}

// Decrypts the stored file into a short-lived plaintext copy in the cache
// dir (still private app storage) so the existing WebView video player can
// open it via a file:// URI. Caller must invoke cleanup() once playback ends.
export async function preparePlayback(id) {
  await ensureDirs();
  const strId = String(id);
  const manifest = await loadManifest();
  const entry = manifest.find(m => m.id === strId);
  if (!entry) throw new Error('קובץ ההורדה לא נמצא');

  const key = await getOrCreateCipherKey();
  const outPath = `${TMP_PLAY_DIR}/${strId}.playback.mp4`;
  if (await RNFS.exists(outPath)) await RNFS.unlink(outPath);
  await xorTransformFile(entry.encPath, outPath, key);

  return {
    uri: 'file://' + outPath,
    cleanup: () => RNFS.unlink(outPath).catch(() => {}),
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
