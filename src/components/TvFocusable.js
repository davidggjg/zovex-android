import React, {useState} from 'react';
import {Platform, TouchableOpacity, requireNativeComponent} from 'react-native';

// תחליף ישיר ל-TouchableOpacity שעובד גם עם שלט של טלוויזיה.
//
// למה זה נחוץ: React Native הליבה (להבדיל מהפורק react-native-tvos) לא תומך
// ב-onFocus/onBlur על Touchable/Pressable — הפרופס נבלעים בשקט. אנדרואיד כן
// מזיז focus בין רכיבים focusable לבד, אבל בלי אירוע ל-JS אי אפשר לצייר שום
// סימון, ולמשתמש זה נראה כאילו השלט מת.
//
// בטלוויזיה: רכיב נייטיב focusable שמדווח focus ומזהה את מקש האישור, ומקבל
// הדגשה אוטומטית. בטלפון: TouchableOpacity רגיל, בלי שינוי התנהגות.
const NativeTvFocusable =
  Platform.isTV ? requireNativeComponent('TvFocusable') : null;

export const IS_TV = Platform.isTV;

export default function TvFocusable({
  style,
  focusStyle,
  onPress,
  onFocusChange,
  hasFocus = false,
  focusChildOnSelect = false,
  allowChildFocus = false,
  // עמעום האפשרות שאינה ממוקדת, בקבוצת בחירה.
  //
  // דווח: "כשיש אפשרות בחירה... קל להבין על איזה אופציה עומדים" — הבקשה
  // הייתה להדגיש את הבחירה ולהחליש את השנייה. הצבעים נשארים בדיוק כפי
  // שהם; מה שמשתנה הוא רק העוצמה, וזה בדיוק ההבדל שמבקשים.
  //
  // opt-in ולא ברירת מחדל: על מסך הבית ממוקד פריט אחד בכל רגע, ועמעום
  // גורף היה מכהה את כל הקטלוג.
  dimUnfocused = false,
  disabled = false,
  activeOpacity = 0.8,
  children,
  ...rest
}) {
  const [focused, setFocused] = useState(false);

  // ── מתי בכלל צריך לערב את JS בתזוזת focus ────────────────────────────
  //
  // דווח: "לוקח לשלט המון זמן להגיב, צריך הרבה לחיצות עד שהוא זז". כל
  // תזוזת חץ היא שתי תזוזות focus, וכל אחת שלחה אירוע ל-JS → setState →
  // רינדור מחדש → עדכון תצוגה בחזרה לנייטיב. ארבע חציות גשר ושני רינדורים
  // של React על כל לחיצה, בזמן שהרשימה ממילא מרנדרת אצווה — וכך הלחיצות
  // הצטברו מאחור.
  //
  // הסימון (מסגרת לבנה, הרמה, עמעום) מצויר בצד הנייטיב ממילא, מיד עם
  // תזוזת החץ. לכן כשאין למסך שימוש אמיתי בידיעה הזאת — והמקרה הזה הוא
  // כל כרטיס וכל כפתור בסרגל — לא מדווחים בכלל, ו-JS לא מעורב בניווט.
  const needsJs = !!(focusStyle || onFocusChange);

  if (IS_TV && NativeTvFocusable) {
    return (
      <NativeTvFocusable
        style={[style, needsJs && focused && focusStyle]}
        hasFocus={hasFocus}
        reportFocus={needsJs}
        dimUnfocused={dimUnfocused}
        focusChildOnSelect={focusChildOnSelect}
        allowChildFocus={allowChildFocus}
        onFocusChange={needsJs ? (e => {
          const f = !!(e && e.nativeEvent && e.nativeEvent.focused);
          if (focusStyle) setFocused(f);
          if (onFocusChange) onFocusChange(f);
        }) : undefined}
        onSelect={() => { if (!disabled && onPress) onPress(); }}>
        {children}
      </NativeTvFocusable>
    );
  }

  return (
    <TouchableOpacity
      style={style}
      onPress={onPress}
      disabled={disabled}
      activeOpacity={activeOpacity}
      {...rest}>
      {children}
    </TouchableOpacity>
  );
}

// אין כאן יותר סגנונות focus. המסגרת הלבנה, ההרמה מעל השכנים והעמעום
// מצוירים כולם בצד הנייטיב ב-TvFocusableView, ברגע שהחץ זז ובלי מעבר
// דרך JS. מה שהיה כאן — ring ו-dim — היה בדיוק מה שחייב סבב React על כל
// לחיצה. הפלטה לא השתנתה: הרקע שהוסר ישב מאחורי תמונת הפוסטר ממילא.
