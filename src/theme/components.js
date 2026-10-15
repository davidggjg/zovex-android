// ── רכיבי UI משותפים של ZOVEX ──────────────────────────────────────────────
//
// נבנים מעל tokens.js ומעל TvFocusable (שלט + מגע). תוספת טהורה: מסך
// מאמץ אותם כשמגיע תורו, ועד אז שום דבר לא משתנה. כל כפתור נגיש בשלט
// (TvFocusable) וגם במגע, עם אזור לחיצה נדיב ו-RTL.

import React from 'react';
import {View, Text, ActivityIndicator, Animated, StyleSheet} from 'react-native';
import TvFocusable from '../components/TvFocusable';
import {colors, spacing, radius, font, IS_TV} from './tokens';

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
//
// "קווים" שנראו על הפוסטרים: הגרסה הקודמת הייתה 6 פסים שווים בשקיפויות
// קבועות, ובין פס לפס רואים קצה ברור. עכשיו: שכבות מצטברות. כל שכבה מתחילה
// ב-i/N מהגובה וממשיכה עד **התחתית** (לא פס בודד), בשקיפות קטנה מאוד, כך
// שהשקיפות הכוללת עולה בצעדים זעירים (עד ~3.5% בנקודה התחתונה) בלי שום תפר בין פסים. הערך
// הכולל בכל נקודה הוא 0.86·t² (t=0 למעלה, 1 למטה) — אותה צורה כמו קודם.
// בטלוויזיה פחות שכבות (מעבד חלש); עדיין הרבה יותר מ-6.
const GRADIENT_N = IS_TV ? 20 : 48;
const GRADIENT_ALPHAS = (() => {
  const out = [];
  let prev = 0;
  for (let i = 0; i < GRADIENT_N; i++) {
    const t = (i + 1) / GRADIENT_N;
    const target = 0.86 * t * t;                       // שקיפות כוללת רצויה
    out.push(Math.max(0, 1 - (1 - target) / (1 - prev))); // תרומת השכבה הזו
    prev = target;
  }
  return out;
})();
export function DarkGradient({style, tint = colors.bg}) {
  return (
    <View style={[StyleSheet.absoluteFill, style]} pointerEvents="none">
      {GRADIENT_ALPHAS.map((a, i) => (
        <View key={i} style={{
          position: 'absolute', left: 0, right: 0, bottom: 0,
          top: `${(i / GRADIENT_N) * 100}%`,
          backgroundColor: tint, opacity: a,
        }} />
      ))}
    </View>
  );
}

// ── זוהר "אורורה" סטטי מאחורי התוכן ─────────────────────────────────────
// רקע שחור שטוח הוא מה שגורם למסך להיראות "בלי טעם". בלי ספריית blur
// (ראה AmbientGlow: אין תלות נייטיבית חדשה) מקרבים זוהר רדיאלי בעיגולים
// קונצנטריים בשקיפות נמוכה — קצוות רכים, אפס JS, אפס אנימציה.
// לא בטלוויזיה: שם כל View נוסף עולה מעבד חלש.
const GLOW_RINGS = 7;
function GlowBlob({size, color, style}) {
  return (
    <View style={[{position: 'absolute', width: size, height: size}, style]}>
      {Array.from({length: GLOW_RINGS}, (_, i) => {
        const k = (i + 1) / GLOW_RINGS;           // 1/7 … 1
        const d = size * (1 - i / GLOW_RINGS);    // קוטר יורד
        return (
          <View key={i} style={{
            position: 'absolute', width: d, height: d, borderRadius: d / 2,
            left: (size - d) / 2, top: (size - d) / 2,
            backgroundColor: color, opacity: 0.045 + k * 0.012,
          }} />
        );
      })}
    </View>
  );
}
export const AuroraBackdrop = React.memo(function AuroraBackdrop({height = 520}) {
  if (IS_TV) return null;
  return (
    <View pointerEvents="none"
      style={{position: 'absolute', top: 0, left: 0, right: 0, height, overflow: 'hidden'}}>
      <GlowBlob size={520} color={colors.auroraViolet} style={{top: -200, left: -160}} />
      <GlowBlob size={460} color={colors.auroraRed} style={{top: -170, right: -190}} />
      <GlowBlob size={420} color={colors.auroraBlue} style={{top: 120, left: -230}} />
    </View>
  );
});

// ── נקודת LIVE פועמת ────────────────────────────────────────────────────
// opacity בלבד עם useNativeDriver — רץ בשרשור הנייטיב, לא נוגע ב-JS.
// בטלוויזיה נקודה סטטית: אנימציה אינסופית שם היא עומס בלי ערך.
export function PulseDot({size = 8, color = colors.primary}) {
  const a = React.useRef(new Animated.Value(1)).current;
  React.useEffect(() => {
    if (IS_TV) return undefined;
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(a, {toValue: 0.25, duration: 700, useNativeDriver: true}),
      Animated.timing(a, {toValue: 1, duration: 700, useNativeDriver: true}),
    ]));
    loop.start();
    return () => loop.stop();
  }, [a]);
  return (
    <Animated.View style={{
      width: size, height: size, borderRadius: size / 2,
      backgroundColor: color, opacity: a,
    }} />
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
    backgroundColor: colors.glass, borderRadius: radius.button,
    borderWidth: StyleSheet.hairlineWidth, borderColor: colors.glassBorder,
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
  AuroraBackdrop, PulseDot,
  EmptyState, LoadingState, ErrorState, Badge,
};
