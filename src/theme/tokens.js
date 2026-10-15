  cardTitle: tv(15, 17),
  body: tv(14, 18),
  label: tv(13, 16),
  caption: tv(12, 15),    // לא קטן מדי, גם בטלפון
  weightBold: '800',
  weightMed: '600',
};

// ── תנועה ───────────────────────────────────────────────────────────────
// אנימציות קצרות וממוקדות; לא להפעיל בכל כרטיס בזמן גלילה.
export const motion = {
  fast: 120,
  base: 180,
  slow: 220,
};

// ── צללים/עומק ──────────────────────────────────────────────────────────
// עומק בשכבות ובצל עדין, לא במסגרות. elevation לאנדרואיד; הצל המפורש
// לטלפון בלבד — בטלוויזיה הוא עולה בביצועים על עשרות כרטיסים ולא נראה.
// נטפליקס שטוח: פוסטרים וסרגלים בלי צל. הצל נשמר רק לשכבות שבאמת צפות
// (מודאל/תפריט), ולכן עומק קטן בלבד — מעל 6 הוא נראה "תלת מימד".
export const elevation = depth => (IS_TV || depth <= 3 ? {} : {
  shadowColor: '#000',
  shadowOpacity: 0.3,
  shadowRadius: Math.min(depth, 6) * 2,
  shadowOffset: {width: 0, height: Math.min(depth, 6)},
  elevation: Math.min(depth, 6),
});

export default {colors, spacing, space, radius, font, motion, elevation, IS_TV};
