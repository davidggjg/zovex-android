// ── רכיבי UI משותפים של ZOVEX ──────────────────────────────────────────────
//
// נבנים מעל tokens.js ומעל TvFocusable (שלט + מגע). תוספת טהורה: מסך
// מאמץ אותם כשמגיע תורו, ועד אז שום דבר לא משתנה. כל כפתור נגיש בשלט
// (TvFocusable) וגם במגע, עם אזור לחיצה נדיב ו-RTL.

import React from 'react';
import {View, Text, ActivityIndicator, StyleSheet} from 'react-native';
import TvFocusable from '../components/TvFocusable';
import {colors, spacing, radius, font} from './tokens';

// ── כפתור ראשי ─────────────────────────────────────────────────────────
export function PrimaryButton({label, onPress, icon, style, hasFocus, disabled}) {
  return (
    <TvFocusable
      style={[s.primary, disabled && s.disabled, style]}
      onPress={onPress}
      hasFocus={hasFocus}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={label}>
      <Text style={s.primaryTxt} numberOfLines={1}>
        {icon ? icon + '  ' : ''}{label}
      </Text>
    </TvFocusable>
  );
}

// ── כפתור משני ─────────────────────────────────────────────────────────
export function SecondaryButton({label, onPress, icon, style, hasFocus, disabled}) {
  return (
    <TvFocusable
      style={[s.secondary, disabled && s.disabled, style]}
      onPress={onPress}
      hasFocus={hasFocus}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={label}>
      <Text style={s.secondaryTxt} numberOfLines={1}>
        {icon ? icon + '  ' : ''}{label}
      </Text>
    </TvFocusable>
  );
}

// ── כותרת מקטע/שורה ─────────────────────────────────────────────────────
// אדום ממוקד: קו דק אדום לצד הכותרת, לא רקע אדום. RTL: הקו בצד ההתחלה.
export function SectionHeader({title, accent = true}) {
  return (
    <View style={s.sectionWrap}>
      {accent ? <View style={s.sectionAccent} /> : null}
      <Text style={s.sectionTxt} numberOfLines={1}>{title}</Text>
    </View>
  );
}

// ── מצב ריק ─────────────────────────────────────────────────────────────
export function EmptyState({emoji = '🎬', title, desc}) {
  return (
    <View style={s.state}>
      <Text style={s.stateEmoji}>{emoji}</Text>
      <Text style={s.stateTitle}>{title}</Text>
      {desc ? <Text style={s.stateDesc}>{desc}</Text> : null}
    </View>
  );
}

// ── מצב טעינה ───────────────────────────────────────────────────────────
export function LoadingState({text = 'טוען…'}) {
  return (
    <View style={s.state}>
      <ActivityIndicator size="large" color={colors.primary} />
      <Text style={[s.stateDesc, {marginTop: spacing.md}]}>{text}</Text>
    </View>
  );
}

// ── מצב שגיאה ───────────────────────────────────────────────────────────
// לא רק צבע: אימוג'י + טקסט + פעולה חוזרת, כדי שהמצב יובן בלי להסתמך על גוון.
export function ErrorState({title = 'משהו השתבש', desc, onRetry, retryLabel = 'נסה שוב'}) {
  return (
    <View style={s.state}>
      <Text style={s.stateEmoji}>⚠️</Text>
      <Text style={s.stateTitle}>{title}</Text>
      {desc ? <Text style={s.stateDesc}>{desc}</Text> : null}
      {onRetry ? (
        <PrimaryButton label={retryLabel} onPress={onRetry}
          style={{marginTop: spacing.lg, minWidth: 160}} />
      ) : null}
    </View>
  );
}

// ── גרדיאנט כהה, בלי ספריית gradient ─────────────────────────────────────
// גרדיאנט אמיתי דורש ספרייה נייטיבית (react-native-linear-gradient) שאינה
// ב-package.json, והכלל של החבילה הוא לא להוסיף תלות לפני בדיקה שאי
// אפשר עם מה שכבר קיים. ערימת שכבות שקיפות עולה בהדרגה היא הקירוב
// המקובל בלי תלות, והיא מספיק טובה בתור מסך (scrim) מאחורי טקסט. סטטי
// לגמרי — בלי JS, בלי focus — ולכן חינם לשים בכל מקום, כולל hero.
const GRADIENT_STEPS = [0, 0.05, 0.15, 0.32, 0.55, 0.8];
export function DarkGradient({style, tint = colors.bg}) {
  return (
    <View style={[StyleSheet.absoluteFill, s.gradientCol, style]} pointerEvents="none">
      {GRADIENT_STEPS.map((op, i) => (
        <View key={i} style={{flex: 1, backgroundColor: tint, opacity: op}} />
      ))}
    </View>
  );
}

// ── Badge — רק כשיש נתון אמיתי (איכות/שנה/סוג) ──────────────────────────
export function Badge({text, tone = 'default'}) {
  if (!text) return null;
  return (
    <View style={[s.badge, tone === 'live' && s.badgeLive]}>
      <Text style={s.badgeTxt} numberOfLines={1}>{text}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  gradientCol: {flexDirection: 'column'},
  primary: {
    backgroundColor: colors.primary, borderRadius: radius.button,
    paddingVertical: 14, paddingHorizontal: spacing.xl,
    alignItems: 'center', justifyContent: 'center', minHeight: 48,
  },
  primaryTxt: {color: '#fff', fontSize: font.body, fontWeight: font.weightBold},
  secondary: {
    backgroundColor: colors.hairline, borderRadius: radius.button,
    paddingVertical: 14, paddingHorizontal: spacing.xl,
    alignItems: 'center', justifyContent: 'center', minHeight: 48,
  },
  secondaryTxt: {color: colors.text, fontSize: font.body, fontWeight: font.weightMed},
  disabled: {opacity: 0.45},

  sectionWrap: {flexDirection: 'row', alignItems: 'center',
                gap: spacing.sm, marginBottom: spacing.md},
  sectionAccent: {width: 3, height: font.section, borderRadius: 2,
                  backgroundColor: colors.primary},
  sectionTxt: {color: colors.text, fontSize: font.section,
               fontWeight: font.weightBold, textAlign: 'right'},

  state: {alignItems: 'center', justifyContent: 'center',
          paddingVertical: spacing.xxxl, paddingHorizontal: spacing.xl},
  stateEmoji: {fontSize: 40, marginBottom: spacing.md},
  stateTitle: {color: colors.text, fontSize: font.section,
               fontWeight: font.weightBold, textAlign: 'center'},
  stateDesc: {color: colors.textSecondary, fontSize: font.body,
              textAlign: 'center', marginTop: spacing.xs, lineHeight: 20},

  badge: {backgroundColor: colors.overlay, borderRadius: 6,
          paddingHorizontal: 6, paddingVertical: 2},
  badgeLive: {backgroundColor: colors.primary},
  badgeTxt: {color: '#fff', fontSize: 9, fontWeight: font.weightBold},
});

export default {
  PrimaryButton, SecondaryButton, SectionHeader, DarkGradient,
  EmptyState, LoadingState, ErrorState, Badge,
};
