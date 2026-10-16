// ── מנוע ניגון לשידורים חיים: VLC, עם שומר-קריסה ─────────────────────────────
//
// למה: על אותה כתובת בדיוק VLC עולה תוך שנייה ו-ExoPlayer לוקח "נצח" (ספקי
// IPTV מגישים זרמי MPEG-TS שברים-למחצה ש-ExoPlayer מתקשה בהם ו-libVLC לא).
//
// למה שומר-קריסה: ניסיון קודם להשתמש ב-libVLC הקריס את האפליקציה בלחיצה על
// פליי, ובלי adb אי אפשר לדעת למה. קריסה נייטיבית אי אפשר ללכוד ב-JS, ולכן
// עושים את זה בדרך עקיפה, בלי שום ממשק:
//
//   1. כש-VLC נטען מסמנים 'pending'.
//   2. ברגע שהוא מדווח שהוא מנגן — או כשהמסך נסגר כרגיל — מסמנים 'ok'.
//   3. אם באפליקציה נפתח מסך שידור חי והסימון עדיין 'pending', סימן שההפעלה
//      הקודמת מתה לפני שהגיעה לנגן (קריסה). מסמנים 'crashed' ומחזירים false:
//      מכאן והלאה שידורים חיים עוברים ל-ExoPlayer, כמו קודם.
//
// הסימון קשור לגרסת האפליקציה: גרסה חדשה (שאולי תיקנה את הקריסה) מקבלת
// הזדמנות חדשה, ולא נשארת חסומה לנצח.
import {Platform} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {APP_VERSION} from './movies';

const KEY = 'zovex_vlc_live_state';

async function read() {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (!raw) return {v: APP_VERSION, s: 'ok'};
    const o = JSON.parse(raw);
    return o && o.v === APP_VERSION ? o : {v: APP_VERSION, s: 'ok'};
  } catch (_) {
    return {v: APP_VERSION, s: 'ok'};
  }
}

function write(s) {
  AsyncStorage.setItem(KEY, JSON.stringify({v: APP_VERSION, s})).catch(() => {});
}

// נקרא פעם אחת בפתיחת מסך שידור חי. true = מותר להשתמש ב-VLC.
export async function vlcLiveAllowed() {
  // libVLC דורשת אנדרואיד 8 (API 26) ומעלה; מתחת לזה נשארים על ExoPlayer.
  if (Platform.OS !== 'android' || Platform.Version < 26) return false;
  const st = await read();
  if (st.s === 'pending') { write('crashed'); return false; }
  return st.s !== 'crashed';
}

export const markVlcPending = () => write('pending');
export const markVlcOk = () => write('ok');
