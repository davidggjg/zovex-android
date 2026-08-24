import React from 'react';
import {Platform, TouchableOpacity, requireNativeComponent} from 'react-native';

// עוטף פריט כך שאפשר לנווט אליו עם שלט ולדעת מתי הוא ב-focus.
//
// בטלוויזיה: רכיב נייטיב (TvFocusable) שהוא focusable אמיתי, מדווח על
// focus/blur ומזהה את מקש האישור בשלט. זה נדרש כי React Native הליבה לא
// תומך ב-onFocus/onBlur על Touchable — הפרופס נבלעים בשקט, ולכן אי אפשר
// לצייר סימון focus ולמשתמש נראה שהשלט לא עובד.
//
// בטלפון: TouchableOpacity רגיל, בלי שום שינוי התנהגות.
const NativeTvFocusable =
  Platform.isTV ? requireNativeComponent('TvFocusable') : null;

export default function TvFocusable({
  isTV,
  style,
  onPress,
  onFocusChange,
  hasFocus = false,
  children,
  ...rest
}) {
  const tv = isTV !== undefined ? isTV : Platform.isTV;

  if (tv && NativeTvFocusable) {
    return (
      <NativeTvFocusable
        style={style}
        hasFocus={hasFocus}
        onFocusChange={e => onFocusChange && onFocusChange(!!e.nativeEvent.focused)}
        onSelect={() => onPress && onPress()}>
        {children}
      </NativeTvFocusable>
    );
  }

  return (
    <TouchableOpacity style={style} onPress={onPress} activeOpacity={0.8} {...rest}>
      {children}
    </TouchableOpacity>
  );
}
