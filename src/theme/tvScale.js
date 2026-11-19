// ── למה הכול נראה לא פרופורציונלי בטלוויזיה ─────────────────────────────────
//
// גוגל מגדירה את בסיס העיצוב לטלוויזיה כ-960×540 dp, ומכשיר תקין מדווח
// על ~960dp רוחב בכל רזולוציית פאנל (720p ב-tvdpi, 1080p ב-xhdpi, 4K
// ב-xxxhdpi — כולם מתכנסים לאותם ~960dp).
//
// אבל חלק לא קטן מקופסאות ומקרני ה-Android TV מדווחים צפיפות 1.0, כלומר
// **1920dp** רוחב. שתי הערות בקוד הזה עצמו מעידות שזה מה שקורה אצלנו:
// "1.25 × 1920 = 2400 פיקסלים" ו-"מוצגים ברוחב ~320px בטלוויזיה".
//
// והנה מה שזה עושה. באפליקציה יש שני סוגי מידות:
//
//   • מידות שנגזרות מהמסך  — CARD_W, HERO_H וכו'. הן יחסיות, ולכן נכונות
//     בכל מכשיר.
//   • מידות קבועות ב-dp    — ‎fontSize: 14‎, ‎padding: 16‎, וכאלה. ב-HomeScreen
//     לבדו יש 80 כאלה.
//
// על מסך של 1920dp הקבוצה הראשונה נשארת נכונה והשנייה מתכווצת ליחס חצי:
// טקסט של 14dp הוא 0.7% מרוחב המסך במקום 1.5%. התוצאה היא בדיוק מה
// שדווח — הבאנר ענק ותופס מסך שלם, ולידו טקסט זעיר ומרווחים דחוסים,
// ושום דבר לא נראה שייך לאותו גודל.
//
// הפתרון כאן: מקדם אחד שמנרמל חזרה לבסיס של גוגל. על מכשיר תקין (960dp)
// הוא 1 ושום דבר לא משתנה; על קופסה שמדווחת 1920dp הוא 2, וכל המידות
// הקבועות מוכפלות — כלומר חוזרות לאותו יחס בדיוק.
//
// מה **לא** מוכפל, בכוונה: רוחב וגובה. הם לרוב או נגזרים מהמסך (ואז
// הכפלה תשבור אותם — ‎maxHeight: screenHeight * 0.7‎ היה הופך לכפול מהמסך)
// או מידה מוחלטת שנבחרה ביד. טיפוגרפיה, מרווחים ורדיוסים הם מה שבאמת
// נשבר כאן, והם מה שמתוקן.

import {Platform, Dimensions} from 'react-native';

import {IS_TV} from './isTv';
export {IS_TV};

// 'screen' ולא 'window': בטלוויזיה אין סרגלי מערכת שמקטינים את החלון,
// ו-'window' מחזיר לפעמים 0 ברגע הראשון.
const {width: TV_W, height: TV_H} = Dimensions.get(IS_TV ? 'screen' : 'window');

// בסיס העיצוב של גוגל לטלוויזיה.
export const TV_BASE_W = 960;

// חסום בין 1 ל-2.5. מתחת ל-1 אין טעם להקטין (מכשיר שמדווח פחות מ-960dp
// כבר מציג הכול גדול), ומעל 2.5 זה כנראה דיווח שגוי ולא מסך אמיתי.
export const TV_SCALE = IS_TV
  ? Math.min(2.5, Math.max(1, TV_W / TV_BASE_W))
  : 1;

/** מכפיל מידה בודדת. שימושי למידות שמחושבות בזמן ריצה ולא ב-StyleSheet. */
export const ts = n => (TV_SCALE === 1 ? n : Math.round(n * TV_SCALE));

// ── אזור בטוח מפני overscan ──────────────────────────────────────────────
// טלוויזיות רבות חותכות את שולי התמונה. גוגל ממליצה על שוליים של 48dp
// בצדדים ו-27dp למעלה ולמטה (5% מבסיס 960×540), כדי שכלום שחייב להיראות
// לא ייחתך. בטלפון זה 0.
export const OVERSCAN_X = IS_TV ? ts(48) : 0;
export const OVERSCAN_Y = IS_TV ? ts(27) : 0;

// המאפיינים שמוכפלים. טיפוגרפיה, מרווחים ורדיוסים בלבד — ראה ההסבר למעלה.
const SCALABLE = new Set([
  'fontSize', 'lineHeight', 'letterSpacing',
  'padding', 'paddingTop', 'paddingBottom', 'paddingLeft', 'paddingRight',
  'paddingHorizontal', 'paddingVertical', 'paddingStart', 'paddingEnd',
  'margin', 'marginTop', 'marginBottom', 'marginLeft', 'marginRight',
  'marginHorizontal', 'marginVertical', 'marginStart', 'marginEnd',
  'gap', 'rowGap', 'columnGap',
  'borderRadius', 'borderTopLeftRadius', 'borderTopRightRadius',
  'borderBottomLeftRadius', 'borderBottomRightRadius',
]);

// radius: 999 הוא "גלולה" ולא מידה — הכפלה שלו חסרת משמעות ורק מנפחת
// מספרים. כל מה שמעל הסף הזה נשאר כפי שהוא.
const PILL = 500;

/**
 * מקבל אובייקט סגנונות ומחזיר אותו עם המידות מוכפלות ב-TV_SCALE.
 *
 * בטלפון, ובטלוויזיה תקינה (960dp), מחזיר את אותו אובייקט בדיוק — אפס
 * עלות ואפס שינוי התנהגות. השימוש:
 *
 *     const styles = StyleSheet.create(tvStyles({ ... }));
 *
 * מחרוזות ('50%', 'auto') ומערכים אינם נוגעים; רק מספרים במאפיינים
 * שברשימה למעלה.
 */
export function tvStyles(sheet) {
  if (TV_SCALE === 1) return sheet;
  const out = {};
  for (const key of Object.keys(sheet)) {
    const rule = sheet[key];
    if (!rule || typeof rule !== 'object' || Array.isArray(rule)) {
      out[key] = rule;
      continue;
    }
    const next = {};
    for (const prop of Object.keys(rule)) {
      const val = rule[prop];
      next[prop] =
        typeof val === 'number' && SCALABLE.has(prop) && Math.abs(val) < PILL
          ? Math.round(val * TV_SCALE)
          : val;
    }
    out[key] = next;
  }
  return out;
}

export default {IS_TV, TV_SCALE, ts, tvStyles, OVERSCAN_X, OVERSCAN_Y, TV_W, TV_H};
