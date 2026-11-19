// ── תופס שגיאות JS לפני שהן הופכות למסך שחור ────────────────────────────────
//
// שגיאה ב-React שלא נתפסת מפרקת את כל עץ הרכיבים: באנדרואיד זה נראה
// כמו מסך שחור או כמו אפליקציה שנסגרה, בלי שום הסבר — ובטלוויזיה אין
// דרך לראות את הלוג. שני דברים קורים כאן:
//
//   1. מוצג מסך שאומר מה קרה, עם כפתור לנסות מחדש, במקום כלום.
//   2. הטקסט נשמר דרך CrashLog, כך שהוא מופיע בהגדרות גם בהפעלה הבאה
//      וניתן לצלם אותו.
//
// זה **לא** תופס קריסה נייטיבית (ExoPlayer, WebView, מפענח וידאו) —
// לאלה יש ה-handler ב-CrashLog.kt. יחד הם מכסים את רוב המקרים.

import React from 'react';
import {View, Text, StyleSheet, NativeModules, Platform} from 'react-native';
import {tvStyles} from '../theme/tvScale';
import TvFocusable from './TvFocusable';

const {CrashLog} = NativeModules;

export default class CrashBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {err: null};
  }

  static getDerivedStateFromError(err) {
    return {err};
  }

  componentDidCatch(err, info) {
    try {
      const text =
        'ZOVEX JS error\n' +
        `מתי: ${new Date().toISOString()}\n` +
        `מכשיר: ${Platform.OS} ${Platform.Version}${Platform.isTV ? ' / TV' : ''}\n` +
        '---\n' +
        `${err?.message || err}\n\n` +
        `${err?.stack || ''}\n\n` +
        `${info?.componentStack || ''}`;
      CrashLog?.recordJsError?.(text.slice(0, 8000)).catch(() => {});
    } catch (_) {}
  }

  render() {
    if (!this.state.err) return this.props.children;
    return (
      <View style={s.wrap}>
        <Text style={s.ttl}>משהו נשבר</Text>
        <Text style={s.body} numberOfLines={6}>
          {String(this.state.err?.message || this.state.err)}
        </Text>
        <Text style={s.hint}>
          הפרטים נשמרו, ואפשר לראות אותם בהגדרות ← דוח קריסה אחרון.
        </Text>
        <TvFocusable style={s.btn} hasFocus onPress={() => this.setState({err: null})}>
          <Text style={s.btnTxt}>נסה שוב</Text>
        </TvFocusable>
      </View>
    );
  }
}

const s = StyleSheet.create(tvStyles({
  wrap: {flex: 1, backgroundColor: '#07070C', alignItems: 'center',
         justifyContent: 'center', paddingHorizontal: 32},
  ttl: {color: '#fff', fontSize: 22, fontWeight: '800', marginBottom: 12},
  body: {color: '#A6A9B3', fontSize: 14, lineHeight: 21, textAlign: 'center',
         marginBottom: 14},
  hint: {color: '#737783', fontSize: 12, textAlign: 'center', marginBottom: 22},
  btn: {backgroundColor: '#E50924', borderRadius: 12, paddingVertical: 12,
        paddingHorizontal: 30},
  btnTxt: {color: '#fff', fontSize: 15, fontWeight: '800'},
}));
