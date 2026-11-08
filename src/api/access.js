// ── חסימת גישה לפי מייל ─────────────────────────────────────────────────────
//
// האתר כבר חוסם, והאפליקציה לא — ולכן מי שנחסם המשיך לצפות דרכה. השרת הוא
// מקור האמת היחיד (‎GET /api/access?email=…‎), והמייל הוא המזהה שזהה בשתי
// הפלטפורמות (מזהה גוגל שונה ביניהן), ולכן חסימה אחת תופסת בשתיהן.
//
// שלושה כללים, וכולם מכוונים לאותו דבר — שהחסימה תתפוס את מי שצריך ולא
// תנעל אף אחד אחר:
//
//   1. אורח אינו נחסם. בלי מייל אין את מי לחסום.
//   2. כשל רשת אינו חוסם. עדיף לתת גישה לרגע מאשר לנעול משתמש תקין בגלל
//      שנייה של רשת, מטוס, או שרת שמתעדכן.
//   3. אין מטמון. חסימה אמורה לתפוס מהר, והבקשה זעירה.
//
// החלק השני בקובץ הוא חנות-מייל זעירה. היא נחוצה כי המשתמש המחובר חי
// ב-state של HomeScreen, בעוד שמסך החסימה חייב לחיות מעל הכול ב-App.js —
// אחרת הוא היה מצויר *בתוך* מסך הבית, שכבר הציג תוכן. בלי החנות, משתמש
// שנכנס לחשבון באמצע ריצה לא היה נבדק עד להפעלה הבאה.

import AsyncStorage from '@react-native-async-storage/async-storage';

const BACKEND_URL = 'https://zovex.duckdns.org';

// חייב להיות זהה ל-USER_KEY ב-HomeScreen — שם נשמר המשתמש המחובר.
const USER_KEY = 'zovex_google_user';

const REQUEST_TIMEOUT_MS = 8000;

/**
 * שואל את השרת אם המייל חסום.
 *
 * מחזיר תמיד אובייקט, לעולם לא זורק: ‎{blocked, message}‎. כל כשל —
 * רשת, timeout, סטטוס לא תקין, JSON פגום — מחזיר ‎blocked:false‎.
 * ‎blocked‎ נבדק בזהות ל-true בכוונה, כדי שתשובה מוזרה (מחרוזת, 1,
 * דף שגיאה של פרוקסי) לא תנעל אף אחד.
 */
export async function checkAccess(email) {
  const e = String(email || '').trim().toLowerCase();
  if (!e) return {blocked: false, message: ''};   // אורח

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(
      `${BACKEND_URL}/api/access?email=${encodeURIComponent(e)}`,
      {signal: controller.signal, headers: {Accept: 'application/json'}},
    );
    if (!res.ok) return {blocked: false, message: ''};
    const data = await res.json();
    if (data?.blocked !== true) return {blocked: false, message: ''};
    return {blocked: true, message: String(data.message || '')};
  } catch (_) {
    return {blocked: false, message: ''};
  } finally {
    clearTimeout(timer);
  }
}

// ── חנות המייל של המשתמש המחובר ─────────────────────────────────────────
let _email = null;
let _loaded = false;
const _listeners = new Set();

function notify() {
  for (const fn of Array.from(_listeners)) {
    try { fn(_email); } catch (_) {}
  }
}

/** נקרא מ-HomeScreen בכניסה, ביציאה, ובשחזור משתמש שמור. */
export function setCurrentEmail(email) {
  const next = email ? String(email).trim().toLowerCase() : null;
  _loaded = true;
  if (next === _email) return;
  _email = next;
  notify();
}

export function getCurrentEmail() {
  return _email;
}

/**
 * קורא את המשתמש השמור מהאחסון. נקרא פעם אחת בעליית האפליקציה, לפני
 * ש-HomeScreen בכלל הורכב — אחרת הבדיקה הראשונה הייתה רצה בלי מייל
 * וכל חסימה הייתה מתגלה רק בחזרה הבאה מהרקע.
 */
export async function loadStoredEmail() {
  if (_loaded) return _email;
  try {
    const raw = await AsyncStorage.getItem(USER_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    setCurrentEmail(parsed?.email || null);
  } catch (_) {
    setCurrentEmail(null);
  }
  return _email;
}

export function subscribeEmail(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

// לבדיקות בלבד.
export function __resetForTests() {
  _email = null;
  _loaded = false;
  _listeners.clear();
}
