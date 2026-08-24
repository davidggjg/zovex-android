import React, {useState} from 'react';
import {Platform, TouchableOpacity, StyleSheet, requireNativeComponent} from 'react-native';

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
  disabled = false,
  activeOpacity = 0.8,
  children,
  ...rest
}) {
  const [focused, setFocused] = useState(false);

  if (IS_TV && NativeTvFocusable) {
    return (
      <NativeTvFocusable
        style={[style, focused && (focusStyle || styles.ring)]}
        hasFocus={hasFocus}
        focusChildOnSelect={focusChildOnSelect}
        onFocusChange={e => {
          const f = !!(e && e.nativeEvent && e.nativeEvent.focused);
          setFocused(f);
          if (onFocusChange) onFocusChange(f);
        }}
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

const styles = StyleSheet.create({
  // המרובע הלבן עצמו מצויר בצד הנייטיב (foreground), כך שהוא לא משנה גודל
  // או מיקום של כלום ומופיע מיד עם תזוזת החץ. כאן נשארת רק הבהרה עדינה של
  // הרקע, שמדגישה את הפריט הממוקד גם על תמונות בהירות.
  ring: {
    backgroundColor: 'rgba(255,255,255,0.14)',
    zIndex: 5,
  },
});
