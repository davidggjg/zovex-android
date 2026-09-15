import {I18nManager} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import STRINGS from './strings';

// ── שפה ──────────────────────────────────────────────────────────────────────
// עברית היא ברירת המחדל ולא "שפה נוספת": כל התוכן עברי, ורוב המשתמשים לא
// ייגעו בהגדרה הזו לעולם.
//
// למה יש כאן חנות קטנה ולא ספריית i18n: האפליקציה צריכה מילון ופונקציה
// אחת. ספרייה חיצונית הייתה מוסיפה תלות, גודל ל-APK ושכבת הגדרות — בשביל
// שני מילונים.

const KEY = 'zovex_lang_v1';
export const LANGS = {he: 'עברית', en: 'English'};
export const DEFAULT_LANG = 'he';

let current = DEFAULT_LANG;
const listeners = new Set();

export function getLanguage() {
  return current;
}

export function isRTL() {
  return current === 'he';
}

// נטען פעם אחת בעליית האפליקציה, לפני הציור הראשון, כדי שלא יהיה הבזק
// של עברית לפני שהאנגלית נטענת.
export async function initLanguage() {
  try {
    const saved = await AsyncStorage.getItem(KEY);
    if (saved && LANGS[saved]) current = saved;
  } catch {}
  return current;
}

export async function setLanguage(lang) {
  if (!LANGS[lang] || lang === current) return {changed: false, needsRestart: false};
  const wasRTL = isRTL();
  current = lang;
  try {
    await AsyncStorage.setItem(KEY, lang);
  } catch {}
  listeners.forEach(fn => { try { fn(current); } catch {} });

  // כיוון הפריסה (RTL/LTR) הוא הגדרה ברמת המערכת ב-React Native, והיא
  // נכנסת לתוקף רק בהפעלה מחדש של האפליקציה. הטקסט יתחלף מיד; היישור
  // והמראה יתיישרו אחרי הפעלה מחדש. לכן מחזירים דגל ולא מעמידים פנים.
  const needsRestart = wasRTL !== isRTL();
  if (needsRestart) {
    try {
      I18nManager.allowRTL(isRTL());
      I18nManager.forceRTL(isRTL());
    } catch {}
  }
  return {changed: true, needsRestart};
}

export function onLanguageChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// t('home.search') → הטקסט בשפה הנוכחית.
// נפילה בשלושה שלבים: השפה הנוכחית → עברית → המפתח עצמו. מפתח חסר יציג
// את המפתח ולא ייפול, כדי שתרגום חלקי לא ישבור מסך.
export function t(key, vars) {
  const dict = STRINGS[current] || STRINGS[DEFAULT_LANG];
  let s = dict[key];
  if (s == null) s = STRINGS[DEFAULT_LANG][key];
  if (s == null) return key;
  if (vars) {
    for (const k of Object.keys(vars)) {
      s = s.split(`{${k}}`).join(String(vars[k]));
    }
  }
  return s;
}
