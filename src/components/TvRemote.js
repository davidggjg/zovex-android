// ── שלט על המסך, למצב הבדיקה ────────────────────────────────────────────────
//
// מה שהופך את זה לבדיקה אמיתית ולא לחיקוי: הכפתורים שולחים KeyEvent
// אמיתי ל-Activity דרך ‎DevTv.sendKey‎. משם זה אותו מסלול בדיוק שרץ על
// טלוויזיה — חיפוש ה-focus הגאומטרי של אנדרואיד, ‎focusSearch‎ ומלכודות
// ה-focus שלנו, ‎requestRectangleOnScreen‎ שגולל עם מרווח, וההגדלה
// והמסגרת ב-TvFocusableView. שום דבר כאן לא מדמה התנהגות; הוא רק לוחץ
// על אותם מקשים.
//
// מוצג רק כשמצב הבדיקה דולק, כלומר אף פעם אצל משתמש רגיל.

import React, {useState} from 'react';
import {View, Text, StyleSheet, NativeModules, PanResponder} from 'react-native';
import {tvStyles} from '../theme/tvScale';

const {DevTv} = NativeModules;

// קודי המקשים של אנדרואיד (KeyEvent). זהים למה ששלט אמיתי שולח.
const KEY = {UP: 19, DOWN: 20, LEFT: 21, RIGHT: 22, CENTER: 23, BACK: 4, MENU: 82};

const press = code => { try { DevTv?.sendKey?.(code); } catch (_) {} };

export default function TvRemote() {
  // גרירה: השלט יושב מעל התוכן, ולפעמים בדיוק מעל מה שרוצים לבדוק.
  const [pos, setPos] = useState({x: 0, y: 0});
  const start = React.useRef({x: 0, y: 0});
  const pan = React.useRef(
    PanResponder.create({
      onMoveShouldSetPanResponder: (_e, g) => Math.abs(g.dx) + Math.abs(g.dy) > 8,
      onPanResponderGrant: () => { start.current = pos; },
      onPanResponderMove: (_e, g) =>
        setPos({x: start.current.x + g.dx, y: start.current.y + g.dy}),
    }),
  ).current;
  // ה-ref נלכד פעם אחת, ולכן start חייב להתעדכן מה-state הנוכחי.
  React.useEffect(() => { start.current = pos; }, [pos]);

  const [open, setOpen] = useState(true);

  if (!open) {
    return (
      <View style={[s.wrap, {transform: [{translateX: pos.x}, {translateY: pos.y}]}]}
        {...pan.panHandlers}>
        <Text style={s.reopen} onPress={() => setOpen(true)}>שלט ▸</Text>
      </View>
    );
  }

  const Btn = ({code, label, style}) => (
    <Text style={[s.btn, style]} onPress={() => press(code)} suppressHighlighting>
      {label}
    </Text>
  );

  return (
    <View style={[s.wrap, {transform: [{translateX: pos.x}, {translateY: pos.y}]}]}
      {...pan.panHandlers}>
      <View style={s.head}>
        <Text style={s.title} onPress={() => setOpen(false)}>שלט בדיקה ▾</Text>
      </View>
      <View style={s.row}><Btn code={KEY.UP} label="▲" /></View>
      <View style={s.row}>
        <Btn code={KEY.LEFT} label="◀" />
        <Btn code={KEY.CENTER} label="OK" style={s.ok} />
        <Btn code={KEY.RIGHT} label="▶" />
      </View>
      <View style={s.row}><Btn code={KEY.DOWN} label="▼" /></View>
      <View style={s.row}>
        <Btn code={KEY.BACK} label="חזור" style={s.wide} />
        <Btn code={KEY.MENU} label="תפריט" style={s.wide} />
      </View>
    </View>
  );
}

const s = StyleSheet.create(tvStyles({
  wrap: {
    position: 'absolute', right: 10, bottom: 90, zIndex: 9999,
    backgroundColor: 'rgba(14,14,18,0.93)', borderRadius: 16, padding: 8,
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.18)', alignItems: 'center',
  },
  head: {paddingBottom: 4},
  title: {color: '#8ab4f8', fontSize: 11, fontWeight: '700'},
  reopen: {color: '#8ab4f8', fontSize: 12, fontWeight: '700', padding: 8},
  row: {flexDirection: 'row', alignItems: 'center', gap: 6, marginVertical: 3},
  btn: {
    color: '#fff', fontSize: 15, fontWeight: '800', textAlign: 'center',
    minWidth: 46, paddingVertical: 10, paddingHorizontal: 6,
    backgroundColor: '#23252E', borderRadius: 10, overflow: 'hidden',
  },
  ok: {backgroundColor: '#E50924', minWidth: 54},
  wide: {minWidth: 62, fontSize: 12},
}));
