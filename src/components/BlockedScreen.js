// ── מסך חסימה ───────────────────────────────────────────────────────────────
//
// אין כאן אף אלמנט שאפשר ללחוץ עליו, וזה לא השמטה אלא הדרישה עצמה.
// באתר הייתה בגרסה הראשונה כפתור התנתקות במסך הזה, והוא הפך את החסימה
// לחסרת ערך: הנחסם מתנתק, נכנס עם מייל אחר, וממשיך לצפות. מאותה סיבה
// אין כאן גם טופס "פנייה לתמיכה" — נחסם שיכול לכתוב דרך האפליקציה עוקף
// את כל הנקודה. הודעת החסימה שמגיעה מהשרת יכולה להגיד איך לפנות.
//
// בטלוויזיה: אין Touchable ואין TvFocusable, ולכן ל-D-pad אין שום יעד
// focus ואי אפשר "להיתקע" על כפתור שלא קיים. הטקסט גדול יותר שם, כי
// קוראים אותו ממרחק של כמה מטרים ולא מ-30 ס"מ.

import React from 'react';
import {View, Text, StyleSheet, StatusBar} from 'react-native';
import {IS_TV} from '../theme/tokens';

const DEFAULT_MESSAGE = 'הגישה שלך נחסמה';

export default function BlockedScreen({message}) {
  const body = String(message || '').trim() || DEFAULT_MESSAGE;
  return (
    <View style={styles.wrap} pointerEvents="none">
      <StatusBar barStyle="light-content" backgroundColor="#000" />
      <View style={styles.card}>
        <Text style={styles.icon}>⛔</Text>
        <Text style={styles.brand}>ZOVEX</Text>
        <Text style={styles.title}>הגישה נחסמה</Text>
        <Text style={styles.message}>{body}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    backgroundColor: '#000',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: IS_TV ? 80 : 26,
  },
  card: {
    width: '100%',
    maxWidth: IS_TV ? 900 : 400,
    alignItems: 'center',
  },
  icon: {
    fontSize: IS_TV ? 72 : 52,
    marginBottom: IS_TV ? 26 : 18,
  },
  brand: {
    color: '#cc1111',
    fontSize: IS_TV ? 20 : 13,
    fontWeight: '900',
    letterSpacing: IS_TV ? 9 : 6,
    marginBottom: IS_TV ? 22 : 14,
    textAlign: 'center',
  },
  title: {
    color: '#ffffff',
    fontSize: IS_TV ? 44 : 26,
    fontWeight: '800',
    textAlign: 'center',
    marginBottom: IS_TV ? 20 : 12,
  },
  message: {
    color: '#b0b0b0',
    fontSize: IS_TV ? 26 : 16,
    lineHeight: IS_TV ? 40 : 26,
    textAlign: 'center',
  },
});
