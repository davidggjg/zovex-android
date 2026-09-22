import React, {useCallback, useEffect, useRef, useMemo, useState} from 'react';
import {View, Text, TouchableOpacity, StyleSheet, StatusBar, NativeModules, Platform} from 'react-native';
import {WebView} from 'react-native-webview';
import TvNativePlayer from '../components/TvNativePlayer';
import NativePlayer, {vtFallbackSrc} from '../components/NativePlayer';
import TvFocusable from '../components/TvFocusable';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {GoogleSignin} from '@react-native-google-signin/google-signin';
import {saveProgress, saveHistory, loadProgress} from '../api/movies';
// שים לב: CastLayer (ואיתו react-native-google-cast) *לא* מיובא כאן ברמת המודול
// בכוונה — הוא נטען עצלנית (require) רק אחרי שווידאנו GMS, כדי שעל מכשירים בלי
// Google Play Services המודול של Cast לא ייטען בכלל.
import SHAKA_PLAYER_SOURCE from '../assets/shakaPlayerSource';
import HLS_JS_SOURCE from '../assets/hlsJsSource';

// Live streams used to feel like they hung forever on some networks. Root
// cause: the player waited on fetching shaka-player.compiled.js (~560KB) and,
// on fallback, hls.js (~370KB) from an external CDN *every time it opened* -
// if that CDN was slow or briefly unreachable for the user's network, there
// was no timeout, so it just sat on the loading spinner indefinitely, even
// though the actual stream URL itself loaded instantly elsewhere. Both
// libraries are now bundled into the app (see src/assets/) and inlined
// straight into the page, so playback never depends on a third-party CDN
// being reachable at all - only the actual video CDN does.
function escapeForInlineScript(js) {
  return js.replace(/<\/script/gi, '<\\/script');
}

const {PipModule} = NativeModules;

const TG_PROXY = 'https://zovex.duckdns.org';

// Maps channel names → numeric IDs (same as CustomVideoPlayer.jsx)
const TG_CHANNELS = {zove8: '7282626428', ZOVE8: '7282626428'};

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
// מנקים כאן, בכניסה, כדי שכל ענפי הזיהוי שלמטה יקבלו כתובת אמיתית.
function cleanVideoRef(raw) {
  let v = (raw || '').trim();
  if (!v) return '';
  const iframe = v.match(/<iframe[^>]*\ssrc=["']([^"']+)["']/i);
  if (iframe) v = iframe[1].trim();
  v = v.replace(/^(?:ttps?):\/\//i, m => (m.toLowerCase().startsWith('ttps') ? 'https://' : 'http://'));
  return v.replace(/&amp;/g, '&');
}

// ── מסלול תיקון-קול ─────────────────────────────────────────────────────────
// ממיר קישור /stream לקישור /vh — HLS עם הווידאו כמו שהוא (-c:v copy, אפס
// עומס) והאודיו מומר ל-AAC בשרת. אותה גישה של Jellyfin ו-Plex, ואותה שהופעלה
// באתר. החתימה זהה (_stream_sig על אותם chat/msg/exp), ולכן ה-?exp=&sig=
// שכבר בקישור עובר כמו שהוא.
//
// נבחר על פני תוסף FFmpeg ל-Media3: זה עובד על כל מכשיר, כולל הטלוויזיה
// החלשה, לא מגדיל את ה-APK, לא דורש בניית NDK, ומשתמש בנתיב שכבר הוכח
// בייצור. אם בעתיד נרצה לפענח על המכשיר כדי להוריד עומס מהשרת — הדרך
// ההיא עדיין פתוחה.
function audioFixSrc(src) {
  if (!src) return null;
  const m = String(src).match(/^(.*)\/stream\/(-?\d+)\/(\d+)(\?.*)?$/);
  if (!m) return null;
  return `${m[1]}/vh/${m[2]}/${m[3]}/index.m3u8${m[4] || ''}`;
}

// ── לאן ללכת כשאין קול, לפי השרת ─────────────────────────────────────────
//
// ‎/vh לבדו הוא מסלול ללא מוצא על חלק מהקטלוג. נמדד על הקובץ שדוד שלח:
//
//     GET /vh/-1003936100530/7170/index.m3u8  →  415
//     {"detail":"אין ftyp — לא קובץ MP4"}
//
// ‎/vh בונה את נקודות החיתוך מה-moov של MP4, ולכן הוא מסרב ל-MKV —
// כלומר דווקא לקבצים שהכי צריכים אותו. זה מה שהשאיר סרט שלם בלי קול גם
// כשהזיהוי עבד מצוין: היעד היה שבור, לא הזיהוי.
//
// ‎/vodinfo יודע לענות: ‎/vh לקובץ MP4 (בדיוק כמו קודם) ו-‎/vt לכל השאר.
// אין תשובה — נשארים על ‎/vh, שזו ההתנהגות הישנה.
function vodInfoSrc(src) {
  if (!src) return null;
  const m = String(src).match(/^(.*)\/stream\/(-?\d+)\/(\d+)(\?.*)?$/);
  if (!m) return null;
  return `${m[1]}/vodinfo/${m[2]}/${m[3]}${m[4] || ''}`;
}

// ── למה זה מנסה יותר מפעם אחת ────────────────────────────────────────────
//
// נמדד מול השרת החי, מדגם אקראי מהקטלוג: חלק לא קטן מהקריאות ל-/vodinfo
// נופל ב-"Connection reset by peer" אחרי 11.1 שניות — באופן עקבי, אותו
// זמן בדיוק. אותם פריטים עונים תוך 2-4 שניות בניסיון חוזר. בקרה של ארבע
// משיכות מקטע גדולות במקביל עברה במלואה, כלומר זו לא הרשת ולא העומס.
//
// מה שזה עשה באפליקציה: כל כישלון כזה נפל אחורה ל-/vh **בניחוש**. ל-AVI
// ול-MKV בלי Cues זה נתיב שאינו יכול לנגן, והתוצאה היא בדיוק
// "לא הצלחתי לנגן את הפריט הזה" על פריט תקין לגמרי.
//
// לכן: מנסים שלוש פעמים לפני שמוותרים, ורק אחר כך נופלים אחורה. השרת
// עדיין צריך תיקון — זה מטפל בתסמין, ובצדק, כי צופה לא אמור לשלם על
// תקלת רשת חולפת.
const VODINFO_TRIES = 3;

async function fetchVodInfo(url) {
  for (let i = 0; i < VODINFO_TRIES; i++) {
    try {
      const ctl = new AbortController();
      const t = setTimeout(() => ctl.abort(), 20000);
      const r = await fetch(url, {signal: ctl.signal});
      clearTimeout(t);
      if (r.ok) return await r.json();
      // 4xx הוא תשובה, לא תקלה — אין טעם לשאול שוב את אותה שאלה
      if (r.status >= 400 && r.status < 500) return null;
    } catch (_) { /* ניתוק או timeout — מנסים שוב */ }
    if (i < VODINFO_TRIES - 1) {
      await new Promise(res => setTimeout(res, 700 * (i + 1)));
    }
  }
  return null;
}

async function resolveFixSrc(src) {
  const info = vodInfoSrc(src);
  const fallback = audioFixSrc(src);
  if (!info) return fallback;
  try {
    const d = await fetchVodInfo(info);
    return d && d.url ? d.url : fallback;
  } catch (_) {
    return fallback;
  }
}

// ── זיכרון של פריטים אילמים ──────────────────────────────────────────────
// בלי זה כל צפייה מתחילה באותו טקס: מנגן בלי קול, אחרי 3.5 שניות מזוהה,
// ורק אז עובר. פעם אחת זה סביר; בכל פרק מחדש זה פשוט מעצבן.
//
// נשמר גם לפי שם הסדרה ולא רק לפי מזהה הפריט: כל 16 פרקי ונסדיי מקודדים
// ב-ec-3, ואין סיבה לגלות את זה מחדש בכל פרק. פרק אחד מלמד על כולם.
const SILENT_KEY = 'zovex_silent_items';

async function loadSilentSet() {
  try {
    return new Set(JSON.parse(await AsyncStorage.getItem(SILENT_KEY) || '[]'));
  } catch (_) { return new Set(); }
}

async function rememberSilent(movie) {
  try {
    const s = await loadSilentSet();
    if (movie.id) s.add(String(movie.id));
    if (movie.series_name) s.add('s:' + movie.series_name);
    await AsyncStorage.setItem(SILENT_KEY,
      JSON.stringify([...s].slice(-500)));
  } catch (_) {}
}

// "1:23:45" לסרט ארוך, "23:45" לפרק. משמש בחלון "להמשיך מאיפה שעצרת".
function fmtClock(sec) {
  const t = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), x = t % 60;
  const pad = n => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(x)}` : `${m}:${pad(x)}`;
}

// ── יציאה מרשימת האילמים ─────────────────────────────────────────────────
// הסימון נשמר לדיסק, שורד הפעלות מחדש, ואין לו תוקף. פרק אחד שזוהה
// בטעות מסמן את כל הסדרה ('s:' + series_name), וכל פרקיה מנותבים מאז
// למסלול תיקון-הקול. אם המסלול הזה נכשל על התוכן הזה — הסדרה מתה
// לתמיד, וזה מה שקרה לסמולוויל: 215 פרקים, וכל השאר בקטלוג עובד.
//
// לכן כשל במסלול תיקון-הקול מוחק את הסימון. הניסיון הבא ייצא מהמסלול
// הרגיל; אם באמת אין שם קול, הזיהוי יסמן שוב. עלות טעות: בדיקה אחת
// של 3.5 שניות. עלות היעדר היציאה: סדרה שבורה בלי דרך לתקן.
async function forgetSilent(movie) {
  try {
    const s = await loadSilentSet();
    let changed = false;
    for (const k of silentKeys(movie)) {
      if (s.delete(k)) changed = true;
    }
    if (changed) {
      await AsyncStorage.setItem(SILENT_KEY, JSON.stringify([...s]));
    }
  } catch (_) {}
}

function silentKeys(movie) {
  const k = [];
  if (movie.id) k.push(String(movie.id));
  if (movie.series_name) k.push('s:' + movie.series_name);
  return k;
}

// אותו קובץ, אבל עם ה-moov בהתחלה.
//
// למה זה חשוב לנגן הנייטיב: השרת מדווח על הפרקים האלה moov_at_end=true על
// קובץ של 1.65GB. כלומר טבלת האינדקס יושבת בסוף, ונגן שמתחיל לנגן חייב
// קודם למשוך את הזנב. ‎/fs מגיש את הכותרת הבנויה מראש (השרת כבר מחזיק
// אותה — faststart_ready=true), וזה מוריד את כל הסיבוב הזה.
function fsSrc(src) {
  if (!src) return null;
  const m = String(src).match(/^(.*)\/stream\/(-?\d+)\/(\d+)(\?.*)?$/);
  if (!m) return null;
  return `${m[1]}/fs/${m[2]}/${m[3]}${m[4] || ''}`;
}

function buildSrc(movie, startTime = 0) {
  const vid = cleanVideoRef(movie.video_id || movie.video_url || '');
  const type = movie.type || 'direct';
  const t = Math.max(0, Math.floor(startTime || 0));
  if (!vid) return null;
  // Decrypted offline downloads are served from a local file:// path - play
  // it directly as a native video, skip every remote-service pattern below.
  if (vid.startsWith('file://')) return vid;
  if (vid.includes('kaltura.com')) return vid;
  const kalturaMatch = vid.match(/^(\d+)\/(\d+)\/([a-zA-Z0-9_]+)$/);
  if (type === 'kaltura' || kalturaMatch) {
    const parts = vid.split('/');
    if (parts.length >= 3)
      return `https://cdnapisec.kaltura.com/p/${parts[0]}/embedPlaykitJs/uiconf_id/${parts[1]}?iframeembed=true&entry_id=${parts[2]}`;
    return null;
  }
  if (type === 'youtube' || vid.includes('youtube.com') || vid.includes('youtu.be')) {
    const m = vid.match(/(?:v=|youtu\.be\/)([^&/?]+)/);
    const base = `https://www.youtube.com/embed/${m ? m[1] : vid}?autoplay=1`;
    return t > 0 ? `${base}&start=${t}` : base;
  }
  if (type === 'drive' || vid.includes('drive.google.com')) {
    const m = vid.match(/\/d\/([^/?]+)/);
    return `https://drive.google.com/file/d/${m ? m[1] : vid}/preview`;
  }
  if (type === 'vimeo' || vid.includes('vimeo.com')) {
    const m = vid.match(/vimeo\.com\/(\d+)/);
    const base = `https://player.vimeo.com/video/${m ? m[1] : vid}?autoplay=1`;
    return t > 0 ? `${base}#t=${t}s` : base;
  }
  if (type === 'dailymotion' || vid.includes('dailymotion.com')) {
    const m = vid.match(/(?:video\/|dai\.ly\/)([a-zA-Z0-9]+)/);
    return `https://www.dailymotion.com/embed/video/${m ? m[1] : vid}?autoplay=1`;
  }
  if (type === 'streamable' || vid.includes('streamable.com')) {
    const m = vid.match(/streamable\.com\/([a-zA-Z0-9]+)/);
    return `https://streamable.com/e/${m ? m[1] : vid}?autoplay=1`;
  }
  if (type === 'rumble' || vid.includes('rumble.com')) {
    const m = vid.match(/(?:embed\/|video\/)([a-zA-Z0-9]+)/);
    return `https://rumble.com/embed/${m ? m[1] : vid}/`;
  }
  if (type === 'archive' || vid.includes('archive.org')) {
    const m = vid.match(/archive\.org\/(?:embed|details)\/([^/?]+)/);
    return `https://archive.org/embed/${m ? m[1] : vid}`;
  }
  if (type === 'kan' || vid.includes('kan.org.il'))
    return `https://www.kan.org.il/General/Embed.aspx?id=${vid}`;
  if (type === 'okru' || vid.includes('ok.ru')) {
    const m = vid.match(/ok\.ru\/video\/(\d+)/);
    return `https://ok.ru/videoembed/${m ? m[1] : vid}`;
  }
  if (type === 'telegram' || vid.includes('t.me')) {
    if (vid.startsWith('http') && !vid.includes('t.me')) return vid;
    const tgId = vid.replace(/^https?:\/\/t\.me\//, '');
    const parts = tgId.split('/').filter(Boolean);
    const chanRaw = parts[0] || '';
    const msgId = parts[parts.length - 1];
    if (/^\d+$/.test(chanRaw) && msgId) return `${TG_PROXY}/stream/${chanRaw}/${msgId}`;
    const numericId = TG_CHANNELS[chanRaw] || TG_CHANNELS[chanRaw.toLowerCase()];
    if (numericId && msgId) return `${TG_PROXY}/stream/${numericId}/${msgId}`;
    return `https://t.me/${tgId}?embed=1&mode=tme`;
  }
  if (type === 'jellyfin') {
    const server = (movie.jellyfin_server || '').replace(/\/$/, '');
    const apiKey = movie.jellyfin_api_key || '';
    return server && vid ? `${server}/web/index.html#!/video?id=${vid}&api_key=${apiKey}` : null;
  }
  return vid.startsWith('http') ? vid : null;
}

function isHlsUrl(src) {
  return src?.includes('.m3u8') || src?.includes('Manifest.ism');
}

function isIframeUrl(src, type) {
  if (!src) return false;
  const iframeTypes = ['youtube', 'drive', 'vimeo', 'dailymotion', 'streamable', 'rumble', 'archive', 'kan', 'okru', 'kaltura', 'jellyfin'];
  if (iframeTypes.includes(type)) return true;
  return ['youtube.com', 'youtu.be', 'drive.google.com', 'vimeo.com', 'dailymotion.com',
    'streamable.com', 'rumble.com', 'archive.org', 'kan.org.il', 'ok.ru', 't.me', 'kaltura.com']
    .some(d => src.includes(d));
}

// בריחת HTML לתוכן ולתכונות. שדות התוכן (title, episode_title, וכתובת
// ה-src של ה-iframe) מגיעים מהקטלוג ומוזרקים ל-HTML של הנגן; בלי בריחה,
// גרש כפול בכתובת שובר מתוך התכונה ומאפשר הזרקת סקריפט — מסוכן במיוחד כאן
// כי ל-WebView יש הרשאות גישה לקבצים מקומיים.
const escHtml = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const escAttr = s => escHtml(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');

function buildPlayerHtml(movie, src, startTime, isLive, hasNext, isTv) {
  const movieJson = JSON.stringify(movie).replace(/</g, '\\u003c').replace(/>/g, '\\u003e');
  const hls = isHlsUrl(src);
  const iframe = isIframeUrl(src, movie.type || 'direct');
  const episodeLabel = movie.episode_title
    ? `פרק ${escHtml(movie.episode_number)} - ${escHtml(movie.episode_title)}`
    : movie.episode_number ? `פרק ${escHtml(movie.episode_number)}` : '';

  if (iframe) {
    return `<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>*{margin:0;padding:0;box-sizing:border-box}body{background:#000;display:flex;flex-direction:column;height:100vh;overflow:hidden}
.bar{flex-shrink:0;height:56px;background:rgba(0,0,0,.85);display:flex;align-items:center;padding:0 14px;direction:rtl;gap:12px}
.x{background:none;border:none;color:#fff;font-size:22px;cursor:pointer;padding:8px;line-height:1;flex-shrink:0}
.ttl{flex:1;text-align:center;color:#fff;font:700 14px/1.3 Arial;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ep{color:rgba(255,255,255,.6);font-size:11px;font-family:Arial}
iframe{flex:1;border:none;width:100%;min-height:0}
</style></head><body>
<div class="bar">
  <button class="x" onclick="postMsg({type:'close'})">✕</button>
  <div style="flex:1;text-align:center">
    <div class="ttl">${escHtml(movie.title)}</div>
    ${episodeLabel ? `<div class="ep">${episodeLabel}</div>` : ''}
  </div>
  <div style="width:36px"></div>
</div>
<iframe src="${escAttr(src)}" allowfullscreen allow="autoplay;encrypted-media;picture-in-picture;fullscreen"></iframe>
<script>
function postMsg(m){try{window.ReactNativeWebView&&window.ReactNativeWebView.postMessage(JSON.stringify(m));}catch{}}
</script>
</body></html>`;
  }

  // Native video — HLS via Shaka Player (→ HLS.js fallback → native), or direct MP4/stream
  return `<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadeInOut{0%{opacity:0;transform:translateY(-50%) scale(.7)}25%{opacity:1;transform:translateY(-50%) scale(1.1)}70%{opacity:1}100%{opacity:0}}
@keyframes resumeFade{0%{opacity:0;transform:translateX(-50%) translateY(-8px)}15%{opacity:1;transform:translateX(-50%) translateY(0)}80%{opacity:1}100%{opacity:0}}
@keyframes liveDot{0%,100%{box-shadow:0 0 0 0 rgba(229,9,20,.6)}50%{box-shadow:0 0 0 6px rgba(229,9,20,0)}}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:100%;height:100%;background:#000;overflow:hidden}
#wrap{position:relative;width:100vw;height:100vh;background:#000;overflow:hidden}
video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000}
#loader{position:absolute;inset:0;z-index:5;background:#000;display:flex;align-items:center;justify-content:center}
/* הודעת כשל ניגון. עד עכשיו כשל של Shaka ושל HLS.js הסתיים בספינר שמסתובב
   לנצח, בלי שום דרך לדעת מה קרה — לא לצופה ולא לנו. */
#playerr{position:absolute;inset:0;z-index:7;background:#000;display:none;
  flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:24px;
  color:#fff;font-family:Arial;text-align:center;direction:rtl}
#playerr .t{font-size:16px;font-weight:700}
#playerr .d{font-size:12px;color:#888;direction:ltr;word-break:break-all;max-width:90%}
.spin{width:44px;height:44px;border:4px solid rgba(255,255,255,.2);border-top:4px solid #e91e8c;border-radius:50%;animation:spin 1s linear infinite}
#overlay{position:absolute;inset:0;z-index:10}
/* direction:ltr במכוון, ולא לפי כיוון הכתיבה: ה-✕ הוא הילד הראשון ולכן
   נשאר תמיד בשמאל — אותו מקום כמו בנגן הנייטיב. סמל השידור לטלוויזיה
   (CastLayer) יושב בימין הפיזי מעל ה-WebView, ולכן הפער מימין: בלעדיו
   כפתור השיתוף נוחת בדיוק מתחתיו. הכותרת יוצאת ~20px מהמרכז בגלל הפער,
   וזה מחיר סביר על סרגל מדורג בנגן-גיבוי. */
#topbar{position:absolute;top:0;left:0;right:0;z-index:30;padding:14px 58px 40px 16px;
  background:linear-gradient(to bottom,rgba(0,0,0,.82) 0%,transparent 100%);
  display:flex;align-items:flex-start;justify-content:space-between;direction:ltr;
  opacity:1;transition:opacity .3s}
.xbtn{background:none;border:none;color:#fff;cursor:pointer;padding:4px;line-height:1;
  display:flex;align-items:center;justify-content:center;-webkit-tap-highlight-color:transparent;outline:none;font-size:26px}
#ttl{flex:1;text-align:center;padding-top:2px}
#ttl .main{color:#fff;font:700 15px/1.3 Arial;text-shadow:0 1px 6px rgba(0,0,0,.9)}
#ttl .sub{color:rgba(255,255,255,.7);font:12px Arial;margin-top:2px}
#bottombar{position:absolute;bottom:0;left:0;right:0;z-index:30;padding:40px 20px 20px;
  background:linear-gradient(to top,rgba(0,0,0,.55) 0%,transparent 100%);
  transition:opacity .3s;opacity:1;direction:ltr}
#progwrap{width:100%;padding:8px 0;margin-bottom:12px;cursor:pointer;touch-action:none}
#progtrack{position:relative;height:3px;background:rgba(255,255,255,.25);border-radius:3px}
#progfill{position:absolute;top:0;left:0;height:100%;width:0%;background:#e91e8c;border-radius:3px}
#progdot{position:absolute;top:50%;left:0%;transform:translate(-50%,-50%);width:13px;height:13px;border-radius:50%;background:#e91e8c;box-shadow:0 0 6px rgba(233,30,140,.7)}
.brow{display:flex;align-items:center;justify-content:space-between}
.bleft{display:flex;align-items:center;gap:16px}
.bright{display:flex;align-items:center;gap:8px}
.ibtn{background:none;border:none;color:#fff;width:42px;height:42px;border-radius:50%;cursor:pointer;
  display:flex;align-items:center;justify-content:center;-webkit-tap-highlight-color:transparent;font-size:20px}
#timestr{color:rgba(255,255,255,.75);font:12px Arial;white-space:nowrap}
.livedot{display:inline-flex;align-items:center;gap:6px;color:#fff;font:900 12px Arial}
.livedot span{width:8px;height:8px;border-radius:50%;background:#e50914;display:inline-block;animation:liveDot 1.5s ease-in-out infinite}
/* חלון המהירות. יושב מעל הפקדים ונסגר בלחיצה מחוץ לו. */
#ratesheet{display:none;position:absolute;right:16px;bottom:96px;z-index:60;
  background:rgba(22,24,30,0.97);border-radius:14px;padding:12px 10px;min-width:170px;
  box-shadow:0 10px 30px rgba(0,0,0,0.5);}
#ratesheet.on{display:block}
.rshead{color:#9aa0a6;font-size:12px;padding:2px 10px 8px;text-align:right}
.rsopt{display:flex;align-items:center;justify-content:space-between;gap:10px;
  color:#e8eaed;font-size:15px;padding:10px 12px;border-radius:9px;cursor:pointer}
.rsopt.sel{background:rgba(47,109,246,0.22);color:#8db4ff;font-weight:700}
#ratelbl{position:absolute;bottom:-2px;left:50%;transform:translateX(-50%);
  font-size:9px;font-weight:700;color:#8db4ff;letter-spacing:-0.3px}
#ratebtn{position:relative}
/* תג שמופיע כל עוד מחזיקים את המסך — משוב שהמהירות אכן השתנתה. */
#holdbadge{display:none;position:absolute;top:22px;left:50%;transform:translateX(-50%);
  z-index:60;background:rgba(0,0,0,0.72);color:#fff;font-size:15px;font-weight:700;
  padding:7px 16px;border-radius:20px;letter-spacing:0.5px}
#holdbadge.on{display:block}
#ctrls{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  display:flex;align-items:center;gap:32px;z-index:20;transition:opacity .3s}
.cbtn{background:none;border:none;color:#fff;width:58px;height:58px;border-radius:50%;cursor:pointer;
  display:flex;align-items:center;justify-content:center;position:relative;-webkit-tap-highlight-color:transparent;outline:none}
.cbtn .num{position:absolute;top:54%;left:50%;transform:translate(-50%,-50%);font:900 10px Arial;color:#fff}
#skipanim{position:absolute;top:40%;z-index:20;animation:fadeInOut .7s ease forwards;display:none}
.skipbox{background:rgba(0,0,0,.55);backdrop-filter:blur(8px);border-radius:18px;padding:14px 22px;
  display:flex;flex-direction:column;align-items:center;gap:4px;border:1px solid rgba(255,255,255,.18)}
.skipbox span{font:700 13px Arial;color:#fff}
#nextcard{display:none;position:absolute;bottom:88px;right:16px;z-index:40;
  background:rgba(10,10,10,.92);border:1px solid rgba(255,255,255,.18);border-radius:14px;
  padding:14px 18px;direction:rtl;min-width:180px}
#nextcard .nclbl{color:rgba(255,255,255,.55);font:11px Arial;margin-bottom:4px}
#nextcard .nctitle{color:#fff;font:700 13px/1.3 Arial}
#nextcard .ncbtn{display:block;margin-top:10px;background:#e91e8c;border:none;color:#fff;
  padding:8px 0;border-radius:8px;font:700 13px Arial;cursor:pointer;width:100%;text-align:center}
#resumetoast{display:none;position:absolute;top:70px;left:50%;transform:translateX(-50%);z-index:50;
  background:rgba(0,0,0,.72);border-radius:20px;padding:8px 18px;color:#fff;font:600 13px Arial;
  white-space:nowrap;pointer-events:none;border:1px solid rgba(255,255,255,.15)}
</style>
</head><body>
<div id="wrap">
  <div id="loader"><div class="spin"></div></div>
  <div id="playerr"><div class="t">לא הצלחתי לנגן את הפריט הזה</div><div class="d" id="playerrd"></div></div>
  <div id="overlay">
    <div id="topbar">
      <button class="xbtn" id="closebtn">✕</button>
      <div id="ttl">
        <div class="main">${escHtml(movie.title)}</div>
        ${episodeLabel ? `<div class="sub">${episodeLabel.replace(/</g, '&lt;')}</div>` : ''}
      </div>
      <button class="xbtn" id="sharebtn" style="font-size:18px">⤴</button>
    </div>
    <div id="ctrls">
      ${isLive ? '' : `<button class="cbtn" id="skipback">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"></polyline><path d="M3.51 15a9 9 0 1 0 .49-3.51"></path></svg>
        <span class="num">10</span></button>`}
      <button class="cbtn" style="width:58px;height:58px" id="playbtn">
        <svg id="pauseIcon" width="28" height="28" viewBox="0 0 28 28" fill="white"><rect x="3" y="3" width="8" height="22" rx="2"/><rect x="17" y="3" width="8" height="22" rx="2"/></svg>
        <svg id="playIcon" width="28" height="28" viewBox="0 0 28 28" fill="white" style="display:none"><polygon points="5,2 26,14 5,26"/></svg>
      </button>
      ${isLive ? '' : `<button class="cbtn" id="skipfwd">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-.49-3.51"></path></svg>
        <span class="num">10</span></button>`}
    </div>
    <div id="bottombar">
      ${isLive ? '' : `<div id="progwrap"><div id="progtrack"><div id="progfill"></div><div id="progdot"></div></div></div>`}
      <div class="brow">
        <div class="bleft">
          <button class="ibtn" id="mutebtn"></button>
          ${isLive
            ? '<div class="livedot"><span></span>LIVE</div>'
            : '<div id="timestr">0:00 / 0:00</div>'}
        </div>
        <div class="bright">
          ${isLive ? '' : '<button class="ibtn" id="ratebtn" title="מהירות"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg><span id="ratelbl"></span></button>'}
          <button class="ibtn" id="pipbtn" style="display:none"></button>
          <button class="ibtn" id="fsbtn"></button>
        </div>
      </div>
    </div>
    <div id="skipanim"><div class="skipbox"><span id="skipicon"></span><span id="skiptext"></span></div></div>
    ${hasNext ? `<div id="nextcard"><div class="nclbl">הפרק הבא</div><div class="nctitle" id="nexttitle"></div><button class="ncbtn" onclick="goNextEp()">המשך לפרק הבא ▶</button></div>` : ''}
    <div id="resumetoast"></div>
    <div id="ratesheet">
      <div class="rshead">מהירות הפעלה</div>
      <div class="rsopts" id="rsopts"></div>
    </div>
    <div id="holdbadge">‏×2 ⏩</div>
  </div>
</div>
${hls ? `<script>${escapeForInlineScript(SHAKA_PLAYER_SOURCE)}</script>
<script>${escapeForInlineScript(HLS_JS_SOURCE)}</script>` : ''}
<script>
(function(){
var MOVIE = ${movieJson};
var START = ${Math.max(0, Math.floor(startTime || 0))};
var IS_LIVE = ${isLive ? 'true' : 'false'};
var IS_TV = ${isTv ? 'true' : 'false'};
var SRC = ${JSON.stringify(src)};
var IS_HLS = ${hls ? 'true' : 'false'};
var STREAM_BACKEND_URL = 'https://zovex.duckdns.org';

function postMsg(m){try{window.ReactNativeWebView&&window.ReactNativeWebView.postMessage(JSON.stringify(m));}catch{}}

// ── MediaSession (lock-screen controls) ──────────────────────
function setupMediaSession(videoEl){
  if(!('mediaSession' in navigator))return;
  var art=MOVIE.poster_url?[{src:MOVIE.poster_url,sizes:'512x512',type:'image/jpeg'}]:[];
  try{navigator.mediaSession.metadata=new MediaMetadata({title:MOVIE.title||'ZOVEX',artist:MOVIE.year?String(MOVIE.year):'',artwork:art});}catch{}
  var seek=function(s){try{videoEl.currentTime=Math.max(0,videoEl.currentTime+s);}catch{}};
  var safe=function(a,h){try{navigator.mediaSession.setActionHandler(a,h);}catch{}};
  safe('play',function(){videoEl.play().catch(function(){});});
  safe('pause',function(){videoEl.pause();});
  safe('seekbackward',function(d){seek(-((d&&d.seekOffset)||10));});
  safe('seekforward',function(d){seek((d&&d.seekOffset)||10);});
  safe('stop',function(){videoEl.pause();videoEl.currentTime=0;});
  try{navigator.mediaSession.playbackState='playing';}catch{}
}
function clearMediaSession(){
  if(!('mediaSession' in navigator))return;
  try{navigator.mediaSession.metadata=null;}catch{}
  ['play','pause','seekbackward','seekforward','stop'].forEach(function(a){
    try{navigator.mediaSession.setActionHandler(a,null);}catch{}
  });
  try{navigator.mediaSession.playbackState='none';}catch{}
}

// ── HLS auto-refresh every 25 min (updates stream URL without page reload) ──
var _refreshTimer=null;
var _currentSrc=[SRC];
function _startRefresh(shakaPl){
  if(_refreshTimer)clearInterval(_refreshTimer);
  _refreshTimer=setInterval(function(){
    fetch(STREAM_BACKEND_URL+'/api/refresh-stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_src:_currentSrc[0]})})
    .then(function(r){return r.ok?r.json():null;}).then(function(d){
      if(!d)return;
      var ns=d.hls_url||d.url;
      if(!ns||ns===_currentSrc[0])return;
      _currentSrc[0]=ns;
      if(shakaPl){try{shakaPl.load(ns).catch(function(){});}catch{}}
    }).catch(function(){});
  },25*60*1000);
}

var HAS_NEXT=${hasNext ? 'true' : 'false'};
var vid=null, dragging=false, hideTimer=null, ctrlsVisible=true, isFullscreen=false, nextShown=false;

var overlay=document.getElementById('overlay');
var loader=document.getElementById('loader');
var ctrls=document.getElementById('ctrls');
var topbar=document.getElementById('topbar');
var bottombar=document.getElementById('bottombar');
var progwrap=document.getElementById('progwrap');
var progfill=document.getElementById('progfill');
var progdot=document.getElementById('progdot');
var timestr=document.getElementById('timestr');
var playIcon=document.getElementById('playIcon');
var pauseIcon=document.getElementById('pauseIcon');
var skipanim=document.getElementById('skipanim');
var NEAR_END=60, NEAR_RATIO=0.95;

function fmt(s){if(!s||isNaN(s)||!isFinite(s))return'0:00';var m=Math.floor(s/60);return m+':'+(Math.floor(s%60)+'').padStart(2,'0');}
function usableDur(v){if(!v)return 0;if(Number.isFinite(v.duration)&&v.duration>0)return v.duration;try{if(v.seekable&&v.seekable.length>0){var e=v.seekable.end(v.seekable.length-1);if(Number.isFinite(e)&&e>0)return e;}}catch{}return 0;}

function onProgress(){
  var dur=usableDur(vid);
  if(!dur||!Number.isFinite(dur))return;
  var finished=(dur-vid.currentTime)<=NEAR_END||(vid.currentTime/dur)>=NEAR_RATIO;
  postMsg({type:'progress',position:finished?0:Math.floor(vid.currentTime),duration:Math.floor(dur)});
}

setInterval(function(){if(vid&&!vid.paused&&!vid.ended)onProgress();},5000);

function updateUI(){
  if(!vid)return;
  var dur=usableDur(vid);
  var ct=vid.currentTime;
  if(!IS_LIVE&&progfill&&dur>0){var pct=(ct/dur)*100;progfill.style.width=pct+'%';if(progdot)progdot.style.left=pct+'%';}
  if(!IS_LIVE&&timestr)timestr.textContent=fmt(ct)+' / '+fmt(dur);
  playIcon.style.display=vid.paused?'block':'none';
  pauseIcon.style.display=vid.paused?'none':'block';
  renderMuteIcon(vid.muted);
  checkNextEp();
}

// כפתור השידור לטלוויזיה הוא רכיב נייטיב מעל ה-WebView, ולכן הוא לא מושפע
// מהשקיפות של הסרגל כאן. מדווחים כל שינוי החוצה כדי שהוא ייעלם ויופיע יחד איתו.
function reportCtrls(v){postMsg({type:'ctrls',visible:!!v});}
function hideCtrls(){
  ctrlsVisible=false;
  [topbar,bottombar,ctrls].forEach(function(el){el.style.opacity=0;el.style.pointerEvents='none';});
  reportCtrls(false);
}

function showCtrls(){
  ctrlsVisible=true;
  overlay.style.opacity=1;topbar.style.opacity=1;bottombar.style.opacity=1;ctrls.style.opacity=1;
  overlay.style.pointerEvents='auto';topbar.style.pointerEvents='auto';bottombar.style.pointerEvents='auto';ctrls.style.pointerEvents='auto';
  reportCtrls(true);
  clearTimeout(hideTimer);
  hideTimer=setTimeout(hideCtrls,3500);
}

function toggleCtrls(){if(ctrlsVisible){clearTimeout(hideTimer);hideCtrls();}else{showCtrls();}}
function checkNextEp(){
  if(!HAS_NEXT||nextShown||!vid||IS_LIVE)return;
  var dur=usableDur(vid);if(!dur||dur<30)return;
  if(dur-vid.currentTime<=300&&vid.currentTime>0){
    nextShown=true;
    var card=document.getElementById('nextcard');
    if(card)card.style.display='block';
    showCtrls();
  }
}
function goNextEp(){postMsg({type:'next_episode'});}

overlay.addEventListener('click',function(e){if(e.target===overlay)toggleCtrls();});
showCtrls();

function togglePlay(){if(!vid)return;vid.paused?vid.play():vid.pause();}
function toggleMute(){
  if(!vid)return;
  vid.muted=!vid.muted;
  updateUI();
}
function renderMuteIcon(muted){
  var btn=document.getElementById('mutebtn');
  if(!btn)return;
  if(muted){
    btn.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="1" y1="1" x2="23" y2="23"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/><path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg>';
  } else {
    btn.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>';
  }
}

function goFullscreen(){
  isFullscreen=!isFullscreen;
  postMsg({type:'fullscreen',enter:isFullscreen});
  renderFsIcon(isFullscreen);
}
function renderFsIcon(fs){
  var btn=document.getElementById('fsbtn');
  if(!btn)return;
  if(fs){
    btn.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"/></svg>';
  } else {
    btn.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>';
  }
}

// ── PiP button ────────────────────────────────────────────────
var pipbtn=document.getElementById('pipbtn');
if(pipbtn&&document.pictureInPictureEnabled){
  pipbtn.style.display='flex';
  pipbtn.innerHTML='<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2"/><rect x="12" y="12" width="8" height="6" rx="1"/></svg>';
  pipbtn.addEventListener('click',function(){
    if(!vid)return;
    try{if(document.pictureInPictureElement){document.exitPictureInPicture().catch(function(){});}
    else{vid.requestPictureInPicture().catch(function(){});}}catch{}
  });
}

function skip(s){
  if(!vid)return;
  vid.currentTime=Math.max(0,vid.currentTime+s);
  var anim=document.getElementById('skipanim');
  var icon=document.getElementById('skipicon');
  var txt=document.getElementById('skiptext');
  if(s>0){anim.style.right='6%';anim.style.left='';icon.textContent='▶▶';txt.textContent='+10 שניות';}
  else{anim.style.left='6%';anim.style.right='';icon.textContent='◀◀';txt.textContent='-10 שניות';}
  anim.style.display='block';
  anim.style.animation='none';anim.offsetHeight;anim.style.animation='fadeInOut .7s ease forwards';
  setTimeout(function(){anim.style.display='none';},700);
}
function doShare(){try{navigator.share&&navigator.share({title:MOVIE.title||'ZOVEX'});}catch{}}

var playbtn=document.getElementById('playbtn');
var skipbackbtn=document.getElementById('skipback');
var skipfwdbtn=document.getElementById('skipfwd');
var sharebtn=document.getElementById('sharebtn');
var closebtn=document.getElementById('closebtn');
if(playbtn)playbtn.addEventListener('click',togglePlay);
if(skipbackbtn)skipbackbtn.addEventListener('click',function(){skip(-10);});
if(skipfwdbtn)skipfwdbtn.addEventListener('click',function(){skip(10);});
if(sharebtn)sharebtn.addEventListener('click',doShare);
if(closebtn)closebtn.addEventListener('click',function(){postMsg({type:'close'});});
document.getElementById('mutebtn').addEventListener('click',toggleMute);
document.getElementById('fsbtn').addEventListener('click',goFullscreen);

/* ── מהירות הפעלה ─────────────────────────────────────────────────────────
   curRate היא המהירות שהצופה בחר. holdRate היא הזמנית של הלחיצה הארוכה;
   היא לא דורסת את הבחירה, ולכן שחרור האצבע חוזר בדיוק למה שנבחר.
   שומרים גם כי הנגן נוצר מחדש במעברים (תיקון קול, פרק הבא) וה-playbackRate
   מתאפס לאחד — setRate נקרא שוב ב-initVideo.                              */
var RATES=[0.5,0.75,1,1.25,1.5,1.75,2];
var curRate=1, holding=false, holdTimer=null, suppressTap=false;
function applyRate(r){try{if(vid)vid.playbackRate=r;}catch(e){}}
function renderRate(){
  var lbl=document.getElementById('ratelbl');
  if(lbl) lbl.textContent = curRate===1 ? '' : (curRate+'x');
  var box=document.getElementById('rsopts'); if(!box) return;
  box.innerHTML = RATES.map(function(r){
    return '<div class="rsopt'+(r===curRate?' sel':'')+'" data-r="'+r+'">'
         + '<span>'+(r===1?'רגיל':r+'x')+'</span><span>'+(r===curRate?'✓':'')+'</span></div>';
  }).join('');
  Array.prototype.forEach.call(box.querySelectorAll('.rsopt'),function(el){
    el.addEventListener('click',function(){
      curRate=parseFloat(el.getAttribute('data-r'));
      if(!holding) applyRate(curRate);
      renderRate(); toggleSheet(false);
    });
  });
}
function toggleSheet(on){
  var sh=document.getElementById('ratesheet'); if(!sh) return;
  var show = (on===undefined) ? !sh.classList.contains('on') : !!on;
  sh.classList.toggle('on',show);
  if(show) showCtrls();
}
var rb=document.getElementById('ratebtn');
if(rb) rb.addEventListener('click',function(e){e.stopPropagation();toggleSheet();});

/* לחיצה ארוכה על המסך = ×2 כל עוד מחזיקים. מתעלמים מנגיעות על הפקדים
   עצמם, אחרת החזקה על כפתור הייתה משנה מהירות במקום ללחוץ עליו.        */
function inControls(t){
  while(t&&t!==document.body){
    var id=t.id||'';
    if(id==='bottombar'||id==='ctrls'||id==='ratesheet'||id==='nextcard') return true;
    t=t.parentNode;
  }
  return false;
}
document.addEventListener('touchstart',function(e){
  if(inControls(e.target)) return;
  var sh=document.getElementById('ratesheet');
  if(sh&&sh.classList.contains('on')){toggleSheet(false);return;}
  holdTimer=setTimeout(function(){
    holding=true; suppressTap=true; applyRate(2);
    var b=document.getElementById('holdbadge'); if(b) b.classList.add('on');
  },450);
},{passive:true});
function endHold(){
  clearTimeout(holdTimer);
  if(holding){
    holding=false; applyRate(curRate);
    var b=document.getElementById('holdbadge'); if(b) b.classList.remove('on');
  }
}
document.addEventListener('touchend',endHold,{passive:true});
document.addEventListener('touchcancel',endHold,{passive:true});
document.addEventListener('touchmove',function(){clearTimeout(holdTimer);},{passive:true});
renderRate();

// ── Seek bar ──────────────────────────────────────────────────
function doSeek(e){
  if(!vid||!progwrap)return;
  var dur=usableDur(vid);if(!dur)return;
  var rect=progwrap.getBoundingClientRect();
  var x=(e.clientX!=null?e.clientX:(e.touches&&e.touches[0]?e.touches[0].clientX:0))-rect.left;
  var ratio=Math.max(0,Math.min(1,x/rect.width));
  vid.currentTime=ratio*dur;updateUI();
}
if(progwrap){
  progwrap.addEventListener('mousedown',function(e){dragging=true;doSeek(e);});
  document.addEventListener('mousemove',function(e){if(dragging)doSeek(e);});
  document.addEventListener('mouseup',function(){dragging=false;});
  progwrap.addEventListener('touchstart',function(e){e.preventDefault();dragging=true;doSeek(e);},{passive:false,capture:true});
  progwrap.addEventListener('touchmove',function(e){if(dragging){e.preventDefault();doSeek(e);}},{passive:false});
  progwrap.addEventListener('touchend',function(){dragging=false;});
}

function initVideo(el){
  // הנגן נוצר מחדש במעברים (תיקון קול, פרק הבא) וה-playbackRate מתאפס.
  try{setTimeout(function(){if(el&&curRate!==1)el.playbackRate=curRate;},0);}catch(e){}
  vid=el;
  function showResume(t){
    var rt=document.getElementById('resumetoast');if(!rt)return;
    var m=Math.floor(t/60);var s=Math.floor(t%60);
    rt.textContent='ממשיך מ-'+m+':'+(s<10?'0'+s:s);
    rt.style.display='block';rt.style.animation='none';rt.offsetHeight;
    rt.style.animation='resumeFade 3s ease forwards';
    setTimeout(function(){rt.style.display='none';},3000);
  }
  window._seekTo=function(t){
    if(!vid)return;
    var doShow=function(){if(t>5)showResume(t);};
    if(vid.readyState>=1){try{vid.currentTime=t;}catch{}doShow();}
    else{vid.addEventListener('loadedmetadata',function(){try{vid.currentTime=t;}catch{}doShow();},{once:true});}
  };
  renderMuteIcon(false);
  renderFsIcon(false);
  updateUI();
  vid.addEventListener('timeupdate',updateUI);
  vid.addEventListener('loadedmetadata',updateUI);
  vid.addEventListener('durationchange',updateUI);
  vid.addEventListener('play',function(){updateUI();postMsg({type:'video_playing',value:true});});
  vid.addEventListener('pause',function(){updateUI();postMsg({type:'video_playing',value:false});});
  vid.addEventListener('ended',function(){onProgress();postMsg({type:'video_playing',value:false});clearMediaSession();});
  vid.addEventListener('waiting',function(){loader.style.display='flex';});
  vid.addEventListener('playing',function(){loader.style.display='none';showCtrls();setupMediaSession(vid);probeAudio();});
  // ── קול שנזרק בשקט ─────────────────────────────────────────────────────
  // תוכן מקודד ב-Dolby Digital Plus (ec-3) לא מתפענח כאן, וה-WebView משמיט
  // את הרצועה **בלי שום אירוע error**: הווידאו מנגן ואין קול. נמדד: 16
  // מתוך 16 פרקי ונסדיי. בדיקה ב-VLC לא מגלה את זה — יש לו מפענח Dolby
  // משלו והוא ניגן אותם כל הזמן.
  // webkitAudioDecodedByteCount הוא הסימן היחיד: הוא נשאר 0 בזמן שהווידאו
  // מתקדם.
  //
  // קודם זו הייתה בדיקה **אחת** 3.5 שניות אחרי 'playing', עם התנאי
  // currentTime>1. זה מרוץ שהבדיקה מפסידה בו: משיכה מטלגרם מתחילה איטי
  // (נמדד TTFB של 6–15 שניות), והניגון בהתחלה מקרטע. אם באותה שנייה
  // בדיוק הזמן עוד לא עבר 1 או שהנגן ממתין — audioProbed כבר דלוק,
  // ההסקלציה לא תקרה לעולם, והצופה מקבל סרט שלם בלי קול. בדיוק זה דווח.
  //
  // עכשיו דוגמים כל שנייה עד שיש תשובה חד-משמעית, ומוסיפים תנאי:
  // webkitVideoDecodedByteCount>0, כלומר הפענוח באמת עובד. ההבחנה הזאת
  // היא מה שמפריד "אין קול" מ"עוד לא התחיל", והיא נכונה גם כשהניגון
  // מקרטע — בלי להישען על הרגע שבו נדגם.
  var audioProbeTimer=null,audioProbeDone=false;
  function stopAudioProbe(){
    if(audioProbeTimer)clearInterval(audioProbeTimer);
    audioProbeTimer=null;
  }
  function probeAudio(){
    // audioProbeDone נפרד מהטיימר בכוונה: בלעדיו מזהה שכבר סיים היה
    // משאיר id דלוק ו-'playing' הבא לא היה מדליק דגימה מחדש, או להפך —
    // מדליק שוב אחרי שכבר דיווחנו.
    if(audioProbeTimer||audioProbeDone)return;
    var ticks=0;
    audioProbeTimer=setInterval(function(){
      ticks++;
      var a=vid.webkitAudioDecodedByteCount;
      var v=vid.webkitVideoDecodedByteCount;
      // אין מדידה בדפדפן הזה, או שנמצא קול — אין מה לבדוק יותר.
      if(a===undefined||a>0){audioProbeDone=true;stopAudioProbe();return;}
      if(v>0&&vid.currentTime>1.5&&!vid.paused){
        audioProbeDone=true;stopAudioProbe();
        postMsg({type:'no_audio',position:vid.currentTime});
        return;
      }
      // תקרה: 90 שניות של קרטוע ואין תשובה — מפסיקים לדגום ולא מסיקים.
      if(ticks>90){audioProbeDone=true;stopAudioProbe();}
    },1000);
  }
  vid.addEventListener('canplay',function(){loader.style.display='none';});
}

// ── כשל ניגון: להגיד מה קרה, לא להסתובב לנצח ─────────────────────────────
// היה: Shaka נכשל, HLS.js נכשל אחריו, והמסך נשאר עם ספינר. הצופה רואה
// "טוען בלי סוף", ואין שום מידע — לא על המסך ולא אצלנו. עכשיו מציגים את
// הקוד ומדווחים ל-RN, שמחליט אם לחזור למסלול המקורי.
var _errShown=false, _shakaErr='';
function playFailed(detail){
  if(_errShown)return;_errShown=true;
  try{
    loader.style.display='none';
    document.getElementById('playerrd').textContent=String(detail||'').slice(0,240);
    document.getElementById('playerr').style.display='flex';
  }catch{}
  postMsg({type:'play_error',detail:String(detail||'').slice(0,240)});
}

// שומר-סף: התקלה שדווחה היא *תקיעה*, לא שגיאה — שום אירוע error לא נורה,
// והספינר פשוט נשאר. אחרי 30 שניות בלי שהניגון התקדם, מציגים את מצב הנגן
// כדי שיהיה מה לקרוא. מסומן soft: זה לא מחזיר את הנגן למסלול המקורי, כי
// טעינה איטית באמת קורית כאן (משיכה מטלגרם) וחבל להרוס אותה בטעות.
setTimeout(function(){
  if(_errShown)return;
  if(vid&&vid.currentTime>0.5)return;
  var b='ריק';
  try{if(vid&&vid.buffered.length)b=vid.buffered.start(0).toFixed(1)+'→'+
    vid.buffered.end(vid.buffered.length-1).toFixed(1);}catch{}
  var d='נתקע: t='+(vid?vid.currentTime.toFixed(2):'אין וידאו')+
    ' ready='+(vid?vid.readyState:'-')+' net='+(vid?vid.networkState:'-')+
    ' buf='+b+' aud='+(vid?vid.webkitAudioDecodedByteCount:'-')+
    (_shakaErr?' | '+_shakaErr:'');
  _errShown=true;
  try{
    document.getElementById('playerrd').textContent=d;
    document.getElementById('playerr').style.display='flex';
  }catch{}
  postMsg({type:'play_error',detail:d,soft:true});
},30000);

if(IS_HLS){
  // ── Shaka Player (primary) ────────────────────────────────
  function startWithShaka(){
    var v=document.createElement('video');
    v.setAttribute('playsinline','');v.setAttribute('autoplay','');
    v.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000';
    document.getElementById('wrap').insertBefore(v,loader);
    initVideo(v);
    window.shaka.polyfill.installAll();
    var player=new window.shaka.Player();
    // buffer/זיכרון:
    // • שידור חי מ-CDN חיצוני: חלון buffer גדול נגד קפיצות/קפיצה-אחורה
    //   (ברירת המחדל של Shaka מכוונת ל-VOD, פחות יציבה לשידור חי מ-CDN).
    // • טלוויזיה חכמה (WebView חלש): מגבילים רזולוציה ל-720p וממעיטים buffer,
    //   כדי לצמצם זיכרון פענוח וידאו ולמנוע קריסת ה-renderer שמוציאה מהאפליקציה.
    var _cfg={};
    if(IS_LIVE){
      _cfg.streaming={bufferingGoal:30,rebufferingGoal:4,retryParameters:{maxAttempts:5,baseDelay:500,backoffFactor:2,timeout:15000}};
      // manifest.retryParameters הוא *נפרד* מ-streaming: הראשון חל על
      // טעינת ה-m3u8 והשני על הסגמנטים. הוגדר כאן רק streaming, ולכן
      // בקשת המניפסט רצה עם ברירות המחדל ונפלה על
      //   shaka 1003 (TIMEOUT) | hls networkError/manifestLoadError
      // הרלה צריך לפתוח את הזרם מול הספק בפנייה הראשונה, וזה לוקח יותר
      // ממה שברירת המחדל מרשה. בדפדפן זה עבד כי שם התקציב נדיב יותר.
      _cfg.manifest={retryParameters:{maxAttempts:4,baseDelay:1000,backoffFactor:2,timeout:35000}};
    }
    if(IS_TV){
      _cfg.restrictions={maxHeight:720};
      _cfg.streaming=Object.assign({bufferingGoal:16,rebufferingGoal:2},_cfg.streaming||{});
    }
    if(Object.keys(_cfg).length)player.configure(_cfg);
    player.attach(v).then(function(){
      return player.load(SRC);
    }).then(function(){
      if(START>1){try{v.currentTime=START;}catch{}}
      v.play().catch(function(){});
      loader.style.display='none';
      _startRefresh(player);
    }).catch(function(e){
      // Shaka failed — fall through to HLS.js. שומרים את הקוד: אם גם HLS.js
      // ייפול, זה מה שיוצג, ובלעדיו אין שום רמז למה שנכשל.
      _shakaErr='shaka '+(e&&e.code!=null?e.code:'?')+
        (e&&e.data?' '+JSON.stringify(e.data).slice(0,90):'');
      player.destroy().catch(function(){});
      v.parentNode&&v.parentNode.removeChild(v);
      vid=null;
      startWithHlsJs();
    });
  }

  // ── HLS.js (fallback) ────────────────────────────────────
  function startWithHlsJs(){
    var v=document.createElement('video');
    v.setAttribute('playsinline','');v.setAttribute('autoplay','');
    v.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000';
    document.getElementById('wrap').insertBefore(v,loader);
    initVideo(v);
    if(window.Hls&&Hls.isSupported()){
      // ברירת המחדל של hls.js למניפסט היא 10 שניות ונסיון אחד — קצר מדי
      // לפנייה ראשונה שמעירה את הרלה. אותו נימוק כמו ב-manifest של Shaka.
      var hls=new Hls({maxBufferLength:IS_TV?16:30,capLevelToPlayerSize:IS_TV,enableWorker:false,
        manifestLoadingTimeOut:35000,manifestLoadingMaxRetry:4,manifestLoadingRetryDelay:1000,
        levelLoadingTimeOut:35000,levelLoadingMaxRetry:4,
        fragLoadingTimeOut:40000,fragLoadingMaxRetry:6});
      hls.loadSource(SRC);hls.attachMedia(v);
      hls.on(Hls.Events.MANIFEST_PARSED,function(){
        if(START>1){try{v.currentTime=START;}catch{}}
        v.play().catch(function(){});loader.style.display='none';
        _startRefresh(null);
      });
      hls.on(Hls.Events.ERROR,function(ev,d){
        if(!d.fatal)return;
        loader.style.display='none';
        playFailed(_shakaErr+' | hls '+d.type+'/'+d.details+
                   (d.reason?' '+d.reason:''));
      });
    } else if(v.canPlayType('application/vnd.apple.mpegurl')){
      v.src=SRC;
      v.addEventListener('loadedmetadata',function(){
        if(START>1){try{v.currentTime=START;}catch{}}
        v.play().catch(function(){});loader.style.display='none';
      });
      v.addEventListener('error',function(){
        playFailed(_shakaErr+' | native '+(v.error?v.error.code+' '+
          (v.error.message||''):'?'));
      });
    } else {
      playFailed(_shakaErr+' | אין תמיכה ב-HLS ב-WebView הזה');
    }
  }

  // Both libraries are already inlined above (no CDN fetch needed) - go
  // straight to Shaka, which falls back to HLS.js internally on failure.
  if(window.shaka){startWithShaka();}else{startWithHlsJs();}
} else {
  // ── Direct video (MP4, stream, telegram proxy, etc.) ─────
  var v=document.createElement('video');
  v.setAttribute('playsinline','');v.setAttribute('autoplay','');
  v.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000';
  v.src=SRC;
  document.getElementById('wrap').insertBefore(v,loader);
  initVideo(v);
  v.addEventListener('loadedmetadata',function(){
    if(START>1){try{v.currentTime=START;}catch{}}
    v.play().catch(function(){});loader.style.display='none';
  });
  v.addEventListener('error',function(){
    loader.style.display='none';
    playFailed('direct '+(v.error?v.error.code+' '+(v.error.message||''):'?'));
  });
}
window.addEventListener('beforeunload',function(){clearMediaSession();if(_refreshTimer)clearInterval(_refreshTimer);});
})();
</script>
</body></html>`;
}

// ── שמירת נקודת הצפייה, אותו כלל בכל הנגנים ──────────────────────────────
//
// לנגן ה-WebView היה כלל: בדקה האחרונה או אחרי 95% הפרק נחשב נצפה ונשמר
// 0, כך שבפעם הבאה הוא מתחיל מההתחלה. לשני הנגנים הנייטיביים — הטלפון
// והטלוויזיה — לא היה. הם שמרו את המיקום הגולמי, ומי שסיים פרק בטלוויזיה
// קיבל בפעם הבאה "להמשיך מ-43:00?" — מהכתוביות.
const NEAR_END_S = 60;
const NEAR_RATIO = 0.95;
// הנגן בטלפון שלח שמירה לשרת פעמיים בשנייה (progressUpdateInterval=500),
// וכל שמירה בשרת קוראת וכותבת את כל קובץ ההתקדמות. עשר שניות מספיקות:
// ביציאה ממילא נשמר המיקום המדויק.
const SAVE_EVERY_MS = 10000;

function progressToSave(pos, dur) {
  if (!(dur > 0)) return pos;
  return (dur - pos <= NEAR_END_S || pos / dur >= NEAR_RATIO) ? 0 : pos;
}

export default function PlayerScreen({route, navigation}) {
  const {movie, startTime = 0, userId = null, seriesEpisodes = null, onLeaveCleanup = null} = route.params;
  const progressRef = useRef({position: startTime, duration: 0});
  const lastSaveRef = useRef({at: 0, finished: false});
  const persistProgress = useCallback((pos, dur) => {
    if (!userId || !(dur > 0)) return;
    const save = progressToSave(pos, dur);
    const finished = save === 0;
    if (!finished && pos <= 5) return;
    const now = Date.now();
    // המעבר ל"נצפה" נשמר מיד — אם יוצאים בדיוק עכשיו, הוא לא יאבד
    const justFinished = finished && !lastSaveRef.current.finished;
    if (!justFinished && now - lastSaveRef.current.at < SAVE_EVERY_MS) return;
    lastSaveRef.current = {at: now, finished};
    saveProgress(movie.id, Math.floor(save), Math.floor(dur), userId);
  }, [movie.id, userId]);
  const seriesEpisodesRef = useRef(seriesEpisodes);
  const isLive = !!movie.is_live;
  const isTv = Platform.isTV; // טלוויזיה חכמה (Android TV) — WebView חלש יותר
  const webViewRef = useRef(null);
  const nextEpIdx = seriesEpisodes ? seriesEpisodes.findIndex(e => e.id === movie.id) : -1;
  const hasNext = nextEpIdx >= 0 && nextEpIdx < (seriesEpisodes?.length ?? 0) - 1;

  // כשהתגלה שהקול נזרק, מנגנים את אותו פריט דרך /vh — מהמקום שבו הצופה
  // היה, לא מההתחלה.
  const [audioFix, setAudioFix] = useState(null); // {src, at} או null
  // נדלק כשמסלול התיקון עצמו נכשל, וחוסם חזרה אליו. בלעדיו: חוזרים למקור,
  // הבדיקה מזהה שוב שאין קול, מחליפים שוב — ולולאה.
  const audioFixFailedRef = useRef(false);
  // המדרגה הראשונה כשמתגלה שאין קול: לנגן את אותו קובץ בנגן הנייטיב, שבו
  // מפענחי ה-FFmpeg שהאפליקציה מביאה איתה מטפלים ב-ec-3. {at} או null.
  const [nativeAudio, setNativeAudio] = useState(null);
  // מכולה שה-WebView לא פותח בכלל (AVI וכו'). ה-WebView הוא דפדפן, ולכן
  // הוא נכשל על אותם קבצים שהאתר נכשל עליהם — ובדיוק כמו באתר, הפתרון
  // הוא /vt, שממיר בשרת. {src, at} או null.
  const [vtFix, setVtFix] = useState(null);
  // אורך הסרט לפי השרת. ראה knownDuration ב-NativePlayer: בהמרה זורמת
  // הנגן לבדו מראה אורך שמטפס בכמה שניות כל פעם.
  const [knownDuration, setKnownDuration] = useState(0);
  // נדלק כשגם ההמרה נכשלה, כדי שלא ננסה אותה שוב ושוב.
  const vtFixFailedRef = useRef(false);

  // ── "להמשיך מאיפה שעצרת?" ────────────────────────────────────────────────
  // שלושת מסלולי הנגינה (WebView, נגן נייטיב, נפילת-קול) קראו כל אחד
  // loadProgress בנפרד ודילגו בשקט. זה גם שכפל קריאות רשת וגם לא השאיר שום
  // מקום לשאול את הצופה. עכשיו יש החלטה אחת שכולם קוראים ממנה:
  //   resumeAt === null → עוד לא הוכרע (החלון פתוח)
  //   resumeAt === 0    → מההתחלה
  //   resumeAt > 0      → להמשיך משם
  const resumeSettled = startTime > 0 || isLive || !userId;
  const [resumeAt, setResumeAt] = useState(resumeSettled ? (startTime || 0) : null);
  const [resumeAsk, setResumeAsk] = useState(null);   // המיקום שעליו שואלים
  useEffect(() => {
    if (resumeSettled) return;
    let alive = true;
    loadProgress(movie.id, userId)
      .then(pos => {
        if (!alive) return;
        // שואלים רק על מיקום משמעותי. חלון על עשר שניות הוא הפרעה, לא שירות.
        if (pos > 60) setResumeAsk(pos);
        else setResumeAt(0);
      })
      .catch(() => { if (alive) setResumeAt(0); });
    return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // כל עוד החלון פתוח הווידאו מושתק ועוצר, כדי שלא ינגן מההתחלה מאחוריו.
  const answerResume = pos => {
    setResumeAt(pos);
    setResumeAsk(null);
    try {
      webViewRef.current?.injectJavaScript(
        'try{var v=document.querySelector("video");v&&v.play();}catch(e){};true;');
    } catch (_) {}
  };
  useEffect(() => {
    if (resumeAsk == null) return;
    try {
      webViewRef.current?.injectJavaScript(
        'try{var v=document.querySelector("video");v&&v.pause();}catch(e){};true;');
    } catch (_) {}
  }, [resumeAsk]);
  // אם כבר ידוע שהפריט (או הסדרה שלו) אילם — נכנסים ישר לנגן הנייטיב, עם
  // קול מהשנייה הראשונה, בלי ההמתנה של הבדיקה.
  useEffect(() => {
    if (isLive || isTv || resumeAt === null) return;
    let alive = true;
    loadSilentSet().then(set => {
      if (!alive || !silentKeys(movie).some(k => set.has(k))) return;
      // המיקום מגיע מנקודת ההחלטה המשותפת: בכניסה ישירה לנגן הנייטיב אין
      // WebView שיקבל הזרקת דילוג, ולכן הוא חייב להיוולד עם המיקום הנכון.
      setNativeAudio({at: resumeAt || 0});
    });
    return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeAt]);

  // ── לשאול את השרת מה יש בקובץ, בלי להסתמך על שום זיהוי ────────────────
  //
  // כל מנגנון שניסינו עד כה שאל את **הנגן** אם יש קול: webkitAudioDecoded-
  // ByteCount ב-WebView, ורצועה שנבחרה ב-ExoPlayer. שניהם נכשלו על אותו
  // קובץ, כל אחד מסיבה אחרת, ובשניהם הכישלון שקט — אין שגיאה, יש תמונה,
  // ואין קול. אי אפשר לבנות על תשובה שהנגן לא תמיד נותן.
  //
  // השרת יודע בוודאות, אבל **צריך לשאול אותו את השאלה הנכונה.** קודם
  // נבדק כאן browser_ok, וזו הייתה טעות: browser_ok הוא פסק דין על
  // דפדפנים, והוא false לכל MKV — בעוד שהנגן הנייטיבי מנגן MKV מצוין
  // ורק קודקי קול מסוימים מפילים אותו. התוצאה הייתה שכל קובץ MKV
  // בקטלוג נשלח להמרה בשרת, שמוגבלת ל-VT_MAX_CONCURRENT מקבילים,
  // וכל צופה מעל התקרה קיבל 503 — "מסך שחור עם וידיאו שבור".
  //
  // native_ok היא השאלה הנכונה: האם הקול בקובץ הזה מפוענח בנגן נייטיבי
  // באנדרואיד. false רק ל-AC-3/E-AC-3/DTS/TrueHD, שאנדרואיד אינו מחייב
  // יצרנים לספק להם מפענח. רק הם מגיעים להמרה; כל השאר מתנגן מקומית.
  //
  // חמש שניות ולא מיד: התשובה הראשונה על פריט עולה לשרת משיכה של 2MB
  // מטלגרם, וזה בדיוק המשאב שהצופה מחכה לו בשניות הראשונות. התשובה
  // נשמרת בשרת לשש שעות, ולכן הצופה הבא מקבל אותה מיד.
  useEffect(() => {
    if (isLive || resumeAt === null || audioFix || vtFix) return;
    const info = vodInfoSrc(buildSrc(movie, 0));
    if (!info) return;
    let alive = true;
    const timer = setTimeout(() => {
      // fetchVodInfo ולא fetch: הקריאה הזאת נופלת מדי פעם בניתוק אחרי
      // 11 שניות (נמדד), וכשהיא נופלת הפריט מנוגן בלי הפסק דין על הקול —
      // כלומר לפעמים בלי קול בכלל. ראה VODINFO_TRIES.
      fetchVodInfo(info)
        .then(d => {
          if (!alive || !d) return;
          if (d.duration) setKnownDuration(d.duration);
          // המרה **רק** כשהשרת אומר במפורש שהקול לא מפוענח כאן.
          // native_ok חסר (שרת ישן, או קובץ שלא ניתן לברר) → לא נוגעים:
          // עדיף ניגון מקומי שאולי אילם מקובץ שלא מתנגן בכלל.
          if (d.native_ok !== false || !d.url) return;
          // ממשיכים מהמקום שבו הצופה נמצא עכשיו, לא מההתחלה.
          const at = Math.max(progressRef.current.position || 0, resumeAt || 0);
          rememberSilent(movie);
          setNativeAudio(null);
          setAudioFix({src: d.url, at});
          setWvKey(k => k + 1);
        })
        .catch(() => {});
    }, 5000);
    return () => { alive = false; clearTimeout(timer); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeAt]);

  const {src, html, isIframe} = useMemo(() => {
    const at = vtFix ? vtFix.at : audioFix ? audioFix.at : (isLive ? 0 : startTime);
    const s = vtFix ? vtFix.src
            : audioFix ? audioFix.src
            : buildSrc(movie, isLive ? 0 : startTime);
    if (!s) return {src: null, html: null, isIframe: false};
    const iframe = isIframeUrl(s, movie.type || 'direct');
    return {
      src: s,
      html: buildPlayerHtml(movie, s, at, isLive, hasNext, isTv),
      isIframe: iframe,
    };
  }, [movie, startTime, isLive, hasNext, isTv, audioFix, vtFix]);

  // ── Chromecast: כפתור שידור לטלוויזיה ──
  // מוצג רק לתוכן ישיר (mp4/HLS) — לא ל-embeds (יוטיוב/דרייב/קלטורה).
  // קריטי: Google Cast נשען על Google Play Services + Cast SDK. במכשירים בלי GMS
  // (טלפוני Qin, חלק מהטלוויזיות) עצם הטעינה של Cast מקריסה את האפליקציה כשנכנסים
  // לנגן. לכן מרכיבים את שכבת ה-Cast (CastLayer) *רק* אחרי שווידאנו ש-GMS זמין.
  const castable = !!src && !isIframe;
  const [castOk, setCastOk] = useState(false);
  // סרגל הבקרה חי בתוך ה-WebView; הוא מדווח על כל הצגה/הסתרה כדי שכפתור
  // השידור הנייטיב שמעליו יופיע וייעלם באותו רגע בדיוק.
  const [ctrlsVisible, setCtrlsVisible] = useState(true);
  // התאוששות מקריסת renderer בטלוויזיה: במקום לזרוק את המשתמש החוצה מיד,
  // טוענים מחדש את הנגן (renderer טרי) עד פעמיים. רק אם גם זה נכשל — יוצאים.
  const [wvKey, setWvKey] = useState(0);
  const crashCountRef = useRef(0);
  useEffect(() => {
    let alive = true;
    // חובה לבדוק את *הערך* שחוזר ולא רק שההבטחה לא נדחתה: במכשירים בלי GMS
    // hasPlayServices לא תמיד זורק — הוא פשוט מחזיר false. הקוד הקודם הדליק
    // את ה-Cast בכל מקרה שלא נזרקה שגיאה, ואז נטענה ספריית Cast שכבר הוסרה
    // מהאפליקציה במכשירים האלה (ראה MainApplication) — והאפליקציה קרסה
    // בכניסה לנגן. ב-App.js אותה בדיקה כבר נעשית נכון.
    // בטלוויזיה אין טעם ב-Chromecast (היא היעד עצמה), ואתחול ה-Cast SDK הוא
    // מקור קריסה ידוע בכניסה לנגן על מכשירי TV — לכן פשוט לא מדליקים אותו שם.
    if (isTv) { setCastOk(false); return () => { alive = false; }; }
    GoogleSignin.hasPlayServices({showPlayServicesUpdateDialog: false})
      .then(ok => { if (alive) setCastOk(ok === true); })
      .catch(() => { if (alive) setCastOk(false); });
    return () => { alive = false; };
  }, [isTv]);
  // טעינה עצלנית: מושכים את react-native-google-cast רק כשיש GMS. על מכשירים בלי
  // GMS (Qin F22/F21 Pro) המודול הזה לא נטען כלל — אפס נגיעה ב-Cast.
  // ה-require עטוף גם ב-try: אם בכל זאת נגיע לכאן בלי המודול המקורי (הוא מוסר
  // מהאפליקציה כשאין GMS), עדיף שכפתור השידור פשוט לא יופיע מאשר שהנגן ייפול.
  const CastLayer = useMemo(() => {
    if (!castOk) return null;
    try {
      return require('../components/CastLayer').default;
    } catch (e) {
      return null;
    }
  }, [castOk]);
  // ל-Chromecast: זרם מהשרת שלנו (/stream) נשלח דרך /cast שממיר אודיו ל-AAC
  // (Chromecast לא מפענח AC3/DTS → אחרת אין קול ב-TV). שאר המקורות כמו שהם.
  const castUrl =
    src && !isHlsUrl(src) && src.includes('/stream/')
      ? src.replace('/stream/', '/cast/')
      : src;
  const pauseLocalForCast = () =>
    webViewRef.current?.injectJavaScript(
      "var v=document.querySelector('video');if(v)v.pause();true;",
    );

  useEffect(() => {
    if (userId) saveHistory(movie.id, movie.title, movie.thumbnail_url, userId);
    return () => {
      StatusBar.setHidden(false, 'fade');
      // בטלוויזיה לא נוגעים בכיוון המסך: היציאה מהנגן החזירה את הפעילות
      // ל"לא-לרוחב", והחלון נפתח מחדש כמו של טלפון — בדיוק ה"מסך קטן כמו
      // של טלפון" שדווח אחרי לחיצה על חזור. טלוויזיה ממילא תמיד לרוחב.
      if (!isTv) {
        PipModule?.setFullscreen(false);
        PipModule?.setLandscape(false);
      }
      PipModule?.setVideoPlaying(false);
      if (!userId) return;
      const {position, duration} = progressRef.current;
      // אותו כלל "נצפה" גם ביציאה: סוף הפרק נשמר כ-0 ולא כמיקום הכתוביות
      if (position > 5 && duration > 0)
        saveProgress(movie.id, Math.floor(progressToSave(position, duration)),
                     Math.floor(duration), userId);
    };
    // isTv הוא Platform.isTV — קבוע לאורך חיי האפליקציה, ולכן הוספתו כאן לא
    // מריצה את ה-effect מחדש אף פעם. נכלל רק כדי שהרשימה תהיה מלאה ואמיתית.
  }, [movie.id, movie.title, movie.thumbnail_url, userId, isTv]);

  // Offline-download playback decrypts to a short-lived temp file before
  // navigating here (see HomeScreen's playDownloadedItem) - delete it once
  // this screen unmounts, whether the user backs out or plays something else.
  useEffect(() => {
    return () => {
      onLeaveCleanup?.();
    };
  }, [onLeaveCleanup]);

  // Load saved progress in background and seek once the video is ready
  useEffect(() => {
    if (!resumeAt || !webViewRef.current) return;
    progressRef.current.position = resumeAt;
    webViewRef.current.injectJavaScript(
      `window._seekTo&&window._seekTo(${Math.floor(resumeAt)});true;`,
    );
  }, [resumeAt]);

  // מעבר לפרק הבא (משמש גם ל-WebView וגם לנגן הנייטיב כשפרק נגמר). מחזיר
  // true אם עבר לפרק הבא, false אם אין (סרט בודד / פרק אחרון).
  const goNextEpisode = () => {
    const eps = seriesEpisodesRef.current;
    if (!eps) return false;
    const idx = eps.findIndex(e => e.id === movie.id);
    const next = idx >= 0 && idx < eps.length - 1 ? eps[idx + 1] : null;
    if (next) {
      navigation.replace('Player', {movie: next, startTime: 0, userId, seriesEpisodes: eps});
      return true;
    }
    return false;
  };

  // ── שני נגנים, ועכשיו בסדר הנכון ────────────────────────────────────────
  //
  // הנגן הנייטיב (ExoPlayer) מפענח דרך מפענחי ה-FFmpeg של Media3 שהאפליקציה
  // מביאה איתה — אותה משפחת מפענחים של VLC. ה-WebView מוגבל למה שהדפדפן
  // המוטמע יודע, וזה פחות.
  //
  // עד כאן הנייטיב שימש רק בטלוויזיה או כנפילה כשזוהה שאין קול, וכל השאר
  // עבר ב-WebView. בפועל התמונה הפוכה: הנייטיב מנגן, וה-WebView נותן מסך
  // שחור עם מטא-דאטה תקינה (duration מוצג, המיקום נשאר 0:00). דוד זיהה
  // את זה בעצמו — "יש שני נגנים, אחד עובד והשני לא".
  //
  // לכן הסדר התהפך: תוכן ישיר (mp4/HLS) הולך לנייטיב, וה-WebView נשאר
  // למה שהנייטיב לא יכול — iframe embeds (יוטיוב, Kaltura, דרייב) — וגם
  // כנפילה-אחורה אם הנייטיב נכשל, מה שלא היה קיים קודם.
  const [nativeFailed, setNativeFailed] = useState(false);
  const useNative = !isIframe && !!src && !nativeFailed;
  // מיקום התחלה לנגן הנייטיב: startTime מפורש, אחרת "המשך צפייה" שנטען מהשרת.
  const [nativeStart, setNativeStart] = useState(startTime || 0);
  // אין כאן עוד מסך שגיאה משלנו: כשהנייטיב נכשל הוא נופל ל-WebView,
  // ואם גם הוא נכשל הוא מציג הודעה משלו מתוך ה-HTML — עם האבחנה
  // (shaka/hls וקוד השגיאה), שמועילה יותר מ"הניגון נכשל" גנרי.
  useEffect(() => {
    if (!useNative || !resumeAt) return;
    progressRef.current.position = resumeAt;
    setNativeStart(resumeAt);
  }, [useNative, resumeAt]);

  const onMessage = event => {
    try {
      const m = JSON.parse(event.nativeEvent.data);
      if (m.type === 'close') {
        navigation.goBack();
      } else if (m.type === 'fullscreen') {
        StatusBar.setHidden(m.enter, 'fade');
        // אותה סיבה כמו בניקוי: בטלוויזיה כפיית כיוון מסך משנה את גודל
        // החלון ומקלקלת את הפריסה. הטלוויזיה כבר לרוחב ומסך-מלא.
        if (!isTv) {
          PipModule?.setFullscreen(!!m.enter);
          PipModule?.setLandscape(!!m.enter);
        }
      } else if (m.type === 'play_error') {
        // הנגן דיווח שהוא לא הצליח. אם זה קרה במסלול תיקון-הקול — חוזרים
        // למקור: סרט בלי קול עדיף על סרט שלא מתחיל. הדגל מונע פינג-פונג,
        // כי אחרי החזרה הבדיקה תזהה שוב שאין קול ותרצה להחליף בחזרה.
        // soft = שומר-הסף, לא שגיאה אמיתית. מציגים ולא מחזירים, כי טעינה
        // איטית מטלגרם היא מצב לגיטימי כאן.
        if (!m.soft) {
          if (vtFix) {
            // גם ההמרה נכשלה. משאירים את השגיאה על המסך ולא חוזרים למקור,
            // שממילא ייכשל — טעינה נוספת רק מאריכה את ההמתנה לשום דבר.
            vtFixFailedRef.current = true;
          } else if (audioFix) {
            audioFixFailedRef.current = true;
            setAudioFix(null);
            setWvKey(k => k + 1);
          } else if (!vtFixFailedRef.current) {
            // ה-WebView לא פתח את הקובץ. זה מה שקורה על AVI ("direct 4"),
            // ובדיוק המקרה שבו /vt פותר באתר. ניסיון אחד דרך ההמרה בשרת,
            // עם אותה חתימה שכבר בקישור.
            const alt = vtFallbackSrc(buildSrc(movie, 0));
            if (alt) {
              setVtFix({src: alt, at: isLive ? 0 : (startTime || 0)});
              setWvKey(k => k + 1);
            }
          }
        }
      } else if (m.type === 'no_audio') {
        // ה-WebView זרק את רצועת הקול. מדרגה ראשונה: אותו קובץ בדיוק, בנגן
        // הנייטיב — שם יש מפענח FFmpeg ל-ec-3, ולכן אין צורך להמיר כלום
        // בשרת ואין איבוד איכות. אם גם הוא ייכשל, onError יוריד אותנו
        // למסלול /vh.
        if (!nativeAudio && !audioFix && !audioFixFailedRef.current) {
          rememberSilent(movie);       // בפעם הבאה ניכנס ישר, בלי ההמתנה
          setNativeAudio({at: Math.max(0, m.position || 0)});
        }
      } else if (m.type === 'video_playing') {
        PipModule?.setVideoPlaying(!!m.value);
      } else if (m.type === 'ctrls') {
        setCtrlsVisible(!!m.visible);
      } else if (m.type === 'next_episode') {
        goNextEpisode();
      } else if (m.type === 'progress' && userId) {
        progressRef.current = {position: m.position, duration: m.duration};
        saveProgress(movie.id, m.position, m.duration, userId);
      }
    } catch (_) {}
  };

  if (!src) {
    // קודם הוצג כאן ריבוע ריק בלי שום טקסט, ולכן כשל בבניית הקישור נראה
    // בדיוק כמו "לחצתי הפעל ולא קרה כלום". עכשיו אומרים מה קרה ומאיפה לצאת.
    return (
      <View style={styles.error}>
        <Text style={styles.errorTitle}>לא נמצא קישור לניגון</Text>
        <Text style={styles.errorBody}>
          לפריט הזה אין כתובת וידאו תקינה. נסה פרק אחר, או דווח לנו כדי שנתקן.
        </Text>
        <TvFocusable style={styles.errorBtn} hasFocus onPress={() => navigation.goBack()}>
          <Text style={styles.errorBtnTxt}>חזרה</Text>
        </TvFocusable>
      </View>
    );
  }

  const episodeLabel = movie.episode_title
    ? `פרק ${movie.episode_number} - ${movie.episode_title}`
    : movie.episode_number ? `פרק ${movie.episode_number}` : '';
  const nextEp = hasNext ? seriesEpisodes[nextEpIdx + 1] : null;

  return (
    <View style={styles.container}>
      {resumeAsk != null ? (
        <View style={styles.resumeWrap}>
          <View style={styles.resumeCard}>
            <Text style={styles.resumeTitle}>להמשיך מאיפה שעצרת?</Text>
            <Text style={styles.resumeSub} numberOfLines={2}>{movie.title || ''}</Text>
            <Text style={styles.resumeTime}>{fmtClock(resumeAsk)}</Text>
            {/* TvFocusable ולא TouchableOpacity: בטלוויזיה Touchable אינו
                יעד focus כלל, ולכן שני הכפתורים האלה היו **בלתי נגישים
                לשלט**. החלון הזה נפתח על כל סרט שיש לו התקדמות שמורה,
                ועוצר את הניגון עד שעונים — כלומר בטלוויזיה הוא פשוט חסם
                את הצפייה. hasFocus מציב את השלט על "המשך מכאן". */}
            <TvFocusable
              hasFocus
              dimUnfocused
              style={[styles.resumeBtn, styles.resumeBtnMain]}
              onPress={() => answerResume(resumeAsk)}>
              <Text style={styles.resumeBtnMainTxt}>המשך מכאן</Text>
            </TvFocusable>
            <TvFocusable dimUnfocused style={styles.resumeBtn}
              onPress={() => answerResume(0)}>
              <Text style={styles.resumeBtnTxt}>התחל מההתחלה</Text>
            </TvFocusable>
          </View>
        </View>
      ) : null}
      {/* בטלפון: ExoPlayer עם מפענחי ה-FFmpeg, אבל עם הפקדים שלנו — דילוג
          ±10, גלגל המהירות וסרגל הגרירה. זה היה עד כה רק מסלול תיקון-הקול,
          ומעכשיו זה המסלול הרגיל: אחרת תוכן רגיל היה נופל לענף הטלוויזיה
          ומקבל את הפקדים המובנים של ExoPlayer, שנראים כמו אפליקציה אחרת.
          בטלוויזיה כן ממשיכים עם המובנים — הם אלה שעובדים עם השלט. */}
      {useNative && !isTv ? (
        <NativePlayer
          // ה-key חייב להשתנות בכל מעבר מסלול. ExoPlayer ממשיך עם המקור
          // הישן כשהוא מקבל רק source חדש, ולכן מעבר ל-/vh היה נראה
          // כאילו לא קרה כלום — עוד שעתיים בלי קול.
          key={audioFix ? 'native-ours-vh' : vtFix ? 'native-ours-vt'
               : nativeAudio ? 'native-ours-audiofix' : 'native-ours'}
          src={fsSrc(src) || src}
          title={movie.title}
          subtitle={episodeLabel}
          // כל מסלול והמיקום שלו. בלי audioFix.at המעבר ל-/vh היה חוזר
          // ל-nativeStart, כלומר מקפיץ את הצופה אחורה לתחילת הסרט.
          startTime={audioFix ? audioFix.at
                   : vtFix ? vtFix.at
                   : nativeAudio ? nativeAudio.at : nativeStart}
          hasNext={hasNext}
          nextLabel={nextEp?.episode_title || ''}
          knownDuration={knownDuration}
          // כבוי. שורת האבחון עשתה את שלה — הקול עובד — ואין סיבה שצופה
          // יראה שמות קודקים על המסך.
          debug={false}
          onClose={() => navigation.goBack()}
          onNext={goNextEpisode}
          onPlayingChange={v => PipModule?.setVideoPlaying(!!v)}
          // אותו מסלול בדיוק של כפתור המסך המלא ב-WebView (הודעת
          // 'fullscreen' ב-onMessage). בטלוויזיה לא מעבירים את הקריאה
          // בכלל — המסך שם מלא ולרוחב, וכפיית כיוון משנה את גודל החלון
          // ומקלקלת את הפריסה. בלי onFullscreen הכפתור לא מוצג.
          onFullscreen={isTv ? undefined : enter => {
            StatusBar.setHidden(enter, 'fade');
            PipModule?.setFullscreen(enter);
            PipModule?.setLandscape(enter);
          }}
          onProgress={(pos, dur) => {
            progressRef.current = {position: pos, duration: dur};
            persistProgress(pos, dur);
          }}
          onEnd={() => { if (!goNextEpisode()) { try { navigation.goBack(); } catch (_) {} } }}
          // הנגן הנייטיב הודיע שיש רצועת קול שהוא לא בחר בה, כלומר אין
          // במכשיר מפענח עבורה. אין כאן שגיאה שתפיל אותנו לענף onError,
          // ולכן זו הדרך היחידה לרדת להמרה בשרת — המדרגה שממילא נועדה
          // בדיוק למקרה הזה. השרת מחליט אם זה /vh או /vt.
          onNoAudio={at => {
            if (audioFix || audioFixFailedRef.current) return;
            resolveFixSrc(buildSrc(movie, 0)).then(fixed => {
              if (!fixed) return;
              rememberSilent(movie);     // בפעם הבאה ניכנס ישר, בלי ההמתנה
              setNativeAudio(null);
              setAudioFix({src: fixed, at: Math.max(0, at || 0)});
              setWvKey(k => k + 1);
            });
          }}
          onError={() => {
            // nativeAudio נבדק במפורש: הענף הזה משמש עכשיו גם לתוכן רגיל,
            // שבו הוא null. בלי הבדיקה הקריאה ל-nativeAudio.at מקריסה את
            // המסך במקום להציג שגיאה — וזה היה תחת onError, כלומר דווקא
            // ברגע שכבר משהו לא בסדר.
            const toWebView = () => {
              // מוחקים את סימון האילמות: אם הגענו לכאן, המסלול שהסימון
              // מנתב אליו לא עבד. בלי זה הסדרה נשארת נעולה עליו לנצח.
              forgetSilent(movie);
              setNativeFailed(true);
              setWvKey(k => k + 1);
            };
            if (nativeAudio && !audioFix) {
              const at = nativeAudio.at;
              resolveFixSrc(buildSrc(movie, 0)).then(fixed => {
                // בלי הענף הזה כשל בבניית הכתובת היה משאיר את המסך תקוע
                // בשקט, במקום ליפול ל-WebView כמו שהיה קודם.
                if (!fixed) return toWebView();
                setNativeAudio(null);
                setAudioFix({src: fixed, at});
                setWvKey(k => k + 1);
              }).catch(toWebView);
            } else {
              // נפילה-אחורה ל-WebView במקום מסך שגיאה ללא מוצא. לא
              // מציבים nativeError: הוא היה מצייר מסך שגיאה מעל ה-WebView
              // שרק התחיל לנסות. ל-WebView יש הודעת שגיאה משלו בתוך
              // ה-HTML (playFailed), וזו שתוצג אם גם הוא ייכשל.
              // מוחקים את סימון האילמות: אם הגענו לכאן, המסלול שהסימון
              // מנתב אליו לא עבד. בלי זה הסדרה נשארת נעולה עליו לנצח.
              forgetSilent(movie);
              setNativeFailed(true);
              setWvKey(k => k + 1);
            }
          }}
        />
      ) : useNative ? (
        <TvNativePlayer
          // key: כשעוברים לכאן באמצע צפייה (תיקון קול) צריך מופע נקי, אחרת
          // ExoPlayer ממשיך עם המקור הישן.
          // ה-key חייב להשתנות בכל מעבר מסלול, אחרת ExoPlayer ממשיך עם
          // המקור הישן כשהוא מקבל רק source חדש — והמעבר להמרה בשרת נראה
          // כאילו לא קרה כלום. בטלפון זה כבר תוקן; כאן זה נשאר, ובדיוק
          // המסך הזה הוא מה שהטלוויזיה מריצה.
          key={audioFix ? 'native-vh' : vtFix ? 'native-vt'
               : nativeAudio ? 'native-audiofix' : 'native'}
          // במסלול תיקון-הקול מגישים דרך /fs — הכותרת בהתחלה במקום בסוף
          // הקובץ. ‎/stream נשאר כשאין המרה כזאת. כתובת HLS של המרה לא
          // עוברת דרך fsSrc (התבנית לא מתאימה) ולכן עוברת כמו שהיא.
          src={(nativeAudio && fsSrc(src)) || src}
          isLive={isLive}
          startTime={audioFix ? audioFix.at
                   : vtFix ? vtFix.at
                   : nativeAudio ? nativeAudio.at : nativeStart}
          debug={!!nativeAudio}
          onProgress={(pos, dur) => {
            progressRef.current = {position: pos, duration: dur};
            persistProgress(pos, dur);
          }}
          onEnd={() => { if (!goNextEpisode()) { try { navigation.goBack(); } catch (_) {} } }}
          // קודם כשל ניגון החזיר את המשתמש אחורה בשקט, וזה נראה בדיוק כמו
          // "לוחץ הפעל וזה מחזיר אותי". עכשיו נשארים במסך ומראים מה נכשל.
          onError={e => {
            // הגענו לנגן הנייטיב רק בגלל תיקון קול? אז יש עוד מדרגה אחת
            // מתחת: ההמרה בשרת. יורדים אליה במקום להיתקע, והשרת מחליט
            // אם זה /vh (קובץ MP4) או /vt (כל השאר).
            if (nativeAudio && !audioFix) {
              const at = nativeAudio.at;
              resolveFixSrc(buildSrc(movie, 0)).then(fixed => {
                if (!fixed) return;
                // שמונה שניות לפני שיורדים למדרגה הבאה, כדי שהשגיאה שמוצגת
                // על המסך תישאר מספיק זמן כדי לקרוא אותה. בלי זה המסך מתחלף
                // מיד וההודעה נעלמת — וזה בדיוק המידע שחסר לנו.
                setTimeout(() => {
                  setNativeAudio(null);
                  setAudioFix({src: fixed, at});
                  setWvKey(k => k + 1);
                }, 8000);
              });
              return;
            }
            // מה שהנייטיב לא הצליח — ה-WebView יקבל הזדמנות, ורק אם גם
            // הוא ייכשל תוצג הודעה (שלו, מתוך ה-HTML). לא מציבים
            // nativeError כדי שלא יכסה את הנגן שרק התחיל לנסות.
            // מוחקים את סימון האילמות: אם הגענו לכאן, המסלול שהסימון
            // מנתב אליו לא עבד. בלי זה הסדרה נשארת נעולה עליו לנצח.
            forgetSilent(movie);
            setNativeFailed(true);
            setWvKey(k => k + 1);
          }}
        />
      ) : (
      <WebView
        key={wvKey}
        ref={webViewRef}
        source={{html}}
        style={styles.player}
        allowsInlineMediaPlayback
        mediaPlaybackRequiresUserAction={false}
        allowsFullscreenVideo
        javaScriptEnabled
        domStorageEnabled
        allowFileAccess
        allowFileAccessFromFileURLs
        allowUniversalAccessFromFileURLs
        startInLoadingState={false}
        onMessage={onMessage}
        // אם ה-renderer של ה-WebView קורס (בעיקר מחוסר זיכרון בטלוויזיה),
        // מנסים לטעון מחדש renderer טרי עד פעמיים; רק אם גם זה נכשל — יוצאים
        // בעדינות במקום שכל האפליקציה תיפול ותיסגר.
        onRenderProcessGone={() => {
          if (crashCountRef.current < 2) {
            crashCountRef.current += 1;
            setWvKey(k => k + 1);
          } else {
            try { navigation.goBack(); } catch (_) {}
          }
        }}
        onMessageForMainFrameOnly={false}
        injectedJavaScriptForMainFrameOnly={false}
        injectedJavaScriptBeforeContentLoadedForMainFrameOnly={false}
        mixedContentMode="always"
        originWhitelist={['*']}
      />
      )}

      {castOk && castable && CastLayer ? (
        <CastLayer
          castUrl={castUrl}
          contentType={isHlsUrl(src) ? 'application/x-mpegurl' : 'video/mp4'}
          isLive={isLive}
          title={movie.title || 'ZOVEX'}
          images={movie.thumbnail_url ? [{url: movie.thumbnail_url}] : []}
          startTime={startTime}
          onCasting={pauseLocalForCast}
          visible={ctrlsVisible}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  // חלון "להמשיך מאיפה שעצרת". יושב מעל הנגן (zIndex גבוה) כי הווידאו
  // ממשיך להתקיים מתחתיו — הוא רק מושהה עד שהצופה עונה.
  resumeWrap: {
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, zIndex: 90,
    backgroundColor: 'rgba(0,0,0,0.82)', alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: 24,
  },
  resumeCard: {
    width: '100%', maxWidth: 380, backgroundColor: '#15181f', borderRadius: 18,
    paddingVertical: 26, paddingHorizontal: 22, alignItems: 'center',
  },
  resumeTitle: {color: '#fff', fontSize: 19, fontWeight: '700', textAlign: 'center'},
  resumeSub: {color: '#9aa0a6', fontSize: 13, marginTop: 6, textAlign: 'center'},
  resumeTime: {color: '#4d8dff', fontSize: 30, fontWeight: '800', marginTop: 12,
               marginBottom: 20, fontVariant: ['tabular-nums']},
  resumeBtn: {width: '100%', paddingVertical: 14, borderRadius: 12, marginTop: 10,
              alignItems: 'center', backgroundColor: 'rgba(255,255,255,0.09)'},
  resumeBtnMain: {backgroundColor: '#2f6df6', marginTop: 0},
  resumeBtnMainTxt: {color: '#fff', fontSize: 16, fontWeight: '700'},
  resumeBtnTxt: {color: '#e8eaed', fontSize: 15, fontWeight: '600'},
  container: {flex: 1, backgroundColor: '#000'},
  player: {flex: 1, backgroundColor: '#000'},
  castBtn: {position: 'absolute', top: 10, right: 12, width: 40, height: 40, tintColor: '#fff', zIndex: 20},
  error: {flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#000', padding: 28},
  errOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.92)',
    justifyContent: 'center', alignItems: 'center', padding: 28, zIndex: 30,
  },
  errorTitle: {color: '#fff', fontSize: 20, fontWeight: '800', marginBottom: 10, textAlign: 'center'},
  errorBody: {color: '#bbb', fontSize: 14, lineHeight: 21, textAlign: 'center', marginBottom: 20},
  errorBtn: {
    backgroundColor: '#e50914', borderRadius: 10,
    paddingHorizontal: 30, paddingVertical: 11, marginTop: 8,
  },
  errorBtnTxt: {color: '#fff', fontSize: 15, fontWeight: '700'},
  errorBox: {width: 60, height: 60, borderRadius: 30, backgroundColor: '#1a1a1a', justifyContent: 'center', alignItems: 'center'},
  errorClose: {width: 24, height: 3, backgroundColor: '#555', borderRadius: 2},
});
