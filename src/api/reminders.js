import {NativeModules, Platform} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

// "הזכר לי" לתוכנית בלוח השידורים.
//
// התזמון עצמו נעשה בצד הנייטיב (ReminderModule → AlarmManager), כך שההתראה
// מגיעה גם כשהאפליקציה סגורה וגם בלי אינטרנט. כאן נשמרת רק *הרשימה* של מה
// שכבר נקבע, כדי שהכפתור יידע להציג "יזכיר" כשחוזרים לאותו ערוץ — האזעקה
// חיה במערכת ואי אפשר לשאול אותה מה קיים.

const {ReminderModule} = NativeModules;
const KEY = 'zovex_reminders';

export const remindersSupported = Platform.OS === 'android' && !!ReminderModule;

export function reminderId(channelSlug, program) {
  return `${channelSlug}_${program.start}`;
}

async function load() {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    const obj = raw ? JSON.parse(raw) : {};
    // ניקוי: תזכורות שזמנן עבר כבר נורו (או פוספסו) ואין טעם לזכור אותן.
    const now = Date.now() / 1000;
    let changed = false;
    for (const k of Object.keys(obj)) {
      if (!obj[k] || obj[k] < now) { delete obj[k]; changed = true; }
    }
    if (changed) await AsyncStorage.setItem(KEY, JSON.stringify(obj));
    return obj;
  } catch (_) {
    return {};
  }
}

async function save(obj) {
  try { await AsyncStorage.setItem(KEY, JSON.stringify(obj)); } catch (_) {}
}

export async function listReminders() {
  return load();
}

/** מחזיר true אם נקבעה תזכורת. false = כבר מאוחר מדי, או שאין תמיכה. */
export async function addReminder(channelSlug, channelTitle, program) {
  if (!remindersSupported) return false;
  const id = reminderId(channelSlug, program);
  const title = `מתחיל עוד רגע: ${program.title || 'תוכנית'}`;
  try {
    const ok = await ReminderModule.schedule(id, program.start, title, channelTitle);
    if (ok) {
      const obj = await load();
      obj[id] = program.start;
      await save(obj);
    }
    return ok;
  } catch (_) {
    return false;
  }
}

export async function removeReminder(channelSlug, program) {
  if (!remindersSupported) return;
  const id = reminderId(channelSlug, program);
  try { await ReminderModule.cancel(id); } catch (_) {}
  const obj = await load();
  delete obj[id];
  await save(obj);
}

/** האם המשתמש בכלל מרשה התראות לאפליקציה. */
export async function canNotify() {
  if (!remindersSupported) return false;
  try { return await ReminderModule.canNotify(); } catch (_) { return false; }
}

export function requestNotificationPermission() {
  try { ReminderModule?.requestPermission?.(); } catch (_) {}
}
