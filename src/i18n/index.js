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
  current = lang;
  try {
    await AsyncStorage.setItem(KEY, lang);
  } catch {}
  listeners.forEach(fn => { try { fn(current); } catch {} });

  // כאן היה allowRTL/forceRTL, וזה היה הבאג. ראה lockLayoutDirection למטה:
  // מנוע הפריסה נשאר שמאל-לימין תמיד, והמראה נקבע אצלנו ברמת הרכיב. החלפת
  // שפה לא נוגעת יותר בכיוון הפריסה בכלל, ולכן גם אין צורך בהפעלה מחדש.
  return {changed: true, needsRestart: false};
}

// ── כיוון הפריסה ─────────────────────────────────────────────────────────────
// I18nManager.forceRTL(true) לא "מיישר טקסט לימין" — הוא הופך את כל מנוע
// הפריסה: flexDirection:'row' נקרא מימין לשמאל, ו-left/right מתחלפים זה
// בזה. התוצאה הייתה היפוך כפול: קוד שכבר ביקש במפורש row-reverse בעברית
// קיבל עוד היפוך מהמנוע וחזר ל-row, וכפתור שהוצב ב-right:12 נחת בשמאל.
// בפועל: ה-✕ וסמל השידור לטלוויזיה נחתו באותה פינה, סרגל ההתקדמות התמלא
// מהצד הלא נכון, וכפתורי ה-±10 התחלפו ביניהם — כל זה רק מהחלפת שפה.
//
// לכן המנוע נעול על LTR, וכל מראה שתלוי בשפה נקבע אצלנו: isRTL() בזמן
// הציור. זו גם ההתנהגות שהייתה לאפליקציה מאז ומתמיד, לפני שנגעתי בזה.
//
// הדגלים האלה נשמרים בצד הנייטיב ונקראים בעליית הגשר, ולכן איפוס שלהם
// נכנס לתוקף רק בהפעלה הבאה. עד אז ltrRow/pinLeft/pinRight מבטלים את
// ההיפוך בזמן הציור, כך שגם ההפעלה הראשונה אחרי העדכון נראית נכון.
export function lockLayoutDirection() {
  try {
    I18nManager.allowRTL(false);
    I18nManager.forceRTL(false);
    if (typeof I18nManager.swapLeftAndRightInRTL === 'function') {
      I18nManager.swapLeftAndRightInRTL(false);
    }
  } catch {}
}

const engineRTL = () => !!I18nManager.isRTL;
const engineSwaps = () =>
  engineRTL() && I18nManager.doLeftAndRightSwapInRTL !== false;

// שורה שנקראת תמיד שמאל-לימין, גם אם המנוע במצב ימין-לשמאל.
export function ltrRow() {
  return {flexDirection: engineRTL() ? 'row-reverse' : 'row'};
}

// מיקום מוחלט בצד פיזי קבוע, ללא תלות בכיוון המנוע.
export function pinLeft(v) {
  return engineSwaps() ? {right: v} : {left: v};
}

export function pinRight(v) {
  return engineSwaps() ? {left: v} : {right: v};
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

// ── שמות קטגוריות ────────────────────────────────────────────────────────────
// הקטגוריות הן נתונים ולא ממשק — הן מגיעות מהקטלוג בעברית. מתרגמים אותן
// לתצוגה בלבד; הערך עצמו נשאר בעברית, אחרת כל השוואת מחרוזת שמסננת לפי
// קטגוריה הייתה נשברת. קטגוריה שאינה במפה מוצגת כמו שהיא.
const CATEGORIES_EN = {
  'הכל': 'All',
  'שידורים חיים': 'Live TV',
  'היסטוריה': 'History',
  'מועדפים': 'Favorites',
  'הורדות': 'Downloads',
  'סרטים': 'Movies',
  'סדרות': 'Series',
  'אנימה': 'Anime',
  'אימה': 'Horror',
  'מארוול': 'Marvel',
  'סרטים ישראלים': 'Israeli Movies',
  'סדרות ישראליות': 'Israeli Series',
  'סדרות טורקיות': 'Turkish Series',
  'סרטים לילדים (מתאים גם למשפחה)': 'Kids & Family',
  'סדרות לילדים': 'Kids Series',
};

export function catName(cat) {
  if (current !== 'en') return cat;
  return CATEGORIES_EN[cat] || cat;
}

// ── שמות ז'אנרים של ערוצים חיים ──────────────────────────────────────────────
// כמו הקטגוריות: השם העברי הוא מפתח הקיבוץ ב-liveGenres.js, אז מתרגמים רק
// לתצוגה. שינוי המפתח עצמו היה מפרק את החלוקה לשורות.
const GENRES_EN = {
  '👶 ילדים': '👶 Kids',
  '⚽ ספורט': '⚽ Sports',
  '📰 חדשות ואקטואליה': '📰 News',
  '🌍 דוקו וטבע': '🌍 Documentary & Nature',
  '🎬 סרטים': '🎬 Movies',
  '📺 סדרות ודרמה': '📺 Series & Drama',
  '✨ לייף סטייל ובידור': '✨ Lifestyle & Entertainment',
  '📡 עוד ערוצים': '📡 More channels',
};

export function genreName(g) {
  if (current !== 'en') return g;
  return GENRES_EN[g] || g;
}
