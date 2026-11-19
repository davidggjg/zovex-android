import React, {useEffect, useState} from 'react';
import {View, Text, TouchableOpacity, StyleSheet, ScrollView, StatusBar, NativeModules} from 'react-native';
import {tvStyles} from '../theme/tvScale';
import {LANGS, getLanguage, setLanguage, t} from '../i18n';
import TvFocusable from '../components/TvFocusable';
import {colors} from '../theme/tokens';
import {APP_VERSION} from '../api/movies';
import {TV_SCALE, TV_W, TV_H, IS_TV} from '../theme/tvScale';

const {CrashLog} = NativeModules;

// מסך הגדרות. כרגע שפה בלבד — נבנה כמסך ולא כחלון קופץ כדי שיהיה מקום
// להגדרות נוספות בלי לשנות מבנה.
export default function SettingsScreen({navigation}) {
  const [lang, setLang] = useState(getLanguage());
  // דוח הקריסה האחרונה. דווח שהאפליקציה מקריסה את הטלוויזיה ביציאה
  // וחזרה, ובלי adb אין שום דרך לראות מה קרה. מוצג כאן כדי שאפשר יהיה
  // פשוט לצלם אותו.
  const [crash, setCrash] = useState('');
  useEffect(() => {
    CrashLog?.getLastCrash?.().then(setCrash).catch(() => {});
  }, []);

  // אין יותר הודעת "צריך להפעיל מחדש": החלפת שפה לא נוגעת בכיוון הפריסה,
  // ולכן היא נכנסת לתוקף מיד ובמלואה. ראה lockLayoutDirection ב-i18n.
  const pick = async code => {
    const {changed} = await setLanguage(code);
    if (!changed) return;
    setLang(code);
  };

  return (
    <View style={s.wrap}>
      <StatusBar barStyle="light-content" backgroundColor="#0f1115" />
      <View style={s.top}>
        <TvFocusable style={s.back} onPress={() => navigation.goBack()} hitSlop={12}>
          <Text style={s.backTxt}>✕</Text>
        </TvFocusable>
        <Text style={s.topTtl}>{t('settings.title')}</Text>
        <View style={s.back} />
      </View>

      <ScrollView contentContainerStyle={s.body}>
        <Text style={s.section}>{t('settings.language')}</Text>
        <View style={s.card}>
          {/* בטלוויזיה TouchableOpacity אינו יעד focus, ולכן מסך ההגדרות
              היה נפתח מתפריט הפרופיל ואי אפשר היה לגעת בכלום — לא להחליף
              שפה ולא לצאת. hasFocus על הראשון מציב את השלט בתוך הרשימה
              ברגע שהמסך נפתח. */}
          {Object.keys(LANGS).map((code, i) => (
            <TvFocusable key={code} hasFocus={i === 0} style={s.row}
              onPress={() => pick(code)}>
              <Text style={[s.rowTxt, code === lang && s.rowTxtSel]}>{LANGS[code]}</Text>
              <Text style={s.check}>{code === lang ? '✓' : ''}</Text>
            </TvFocusable>
          ))}
        </View>
        <Text style={s.hint}>{t('settings.languageHint')}</Text>

        <Text style={s.section}>{t('settings.about')}</Text>
        <View style={s.card}>
          <View style={s.row}>
            <Text style={s.rowTxt}>ZOVEX</Text>
            <Text style={s.dim}>{t('settings.version', {v: APP_VERSION})}</Text>
          </View>
          {/* יש מי שמוכר את האפליקציה ואת האתר שלנו. מי ששילם אינו חושד
              בכך מעצמו — מבחינתו הוא קנה מוצר — ולכן ההודעה יושבת כאן,
              במקום שאליו הוא מגיע כשהוא מחפש "מי עומד מאחורי זה", ולא
              רק בכותרת התחתונה שעוברים עליה במהירות. */}
          <View style={s.free}>
            <Text style={s.freeTtl}>{t('free.title')}</Text>
            <Text style={s.freeTxt}>{t('free.body')}</Text>
            <Text style={s.freeTxt}>{t('free.paid')}</Text>
            <TvFocusable style={s.freeBtn}
              onPress={() => navigation.navigate('Home', {openSupport: true})}>
              <Text style={s.freeBtnTxt}>{t('free.cta')}</Text>
            </TvFocusable>
          </View>
        </View>
        {/* אבחון. מוצג רק כשיש מה להציג, כך שבשגרה המסך לא משתנה. */}
        {!!crash && (
          <>
            <Text style={s.section}>דוח קריסה אחרון</Text>
            <View style={s.card}>
              <Text style={s.crashTxt} selectable>{crash}</Text>
              <TvFocusable style={s.freeBtn}
                onPress={() => {
                  CrashLog?.clearLastCrash?.().catch(() => {});
                  setCrash('');
                }}>
                <Text style={s.freeBtnTxt}>נקה את הדוח</Text>
              </TvFocusable>
            </View>
          </>
        )}

        {/* פרטי התצוגה. זה מה שמאפשר לדעת אם המכשיר מדווח 960dp כמו
            שגוגל מצפה או 1920dp, ולכן באיזה מקדם הפריסה רצה — בדיוק
            השאלה שאי אפשר לענות עליה מרחוק. */}
        {IS_TV && (
          <>
            <Text style={s.section}>תצוגה</Text>
            <View style={s.card}>
              <View style={s.row}>
                <Text style={s.rowTxt}>גודל מסך</Text>
                <Text style={s.dim}>{TV_W}×{TV_H} dp</Text>
              </View>
              <View style={s.row}>
                <Text style={s.rowTxt}>מקדם התאמה</Text>
                <Text style={s.dim}>×{TV_SCALE.toFixed(2)}</Text>
              </View>
            </View>
          </>
        )}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create(tvStyles({
  crashTxt: {color: '#c9ccd4', fontSize: 11, lineHeight: 16, padding: 12,
             writingDirection: 'ltr', textAlign: 'left'},
  wrap: {flex: 1, backgroundColor: colors.bg},
  top: {flexDirection: 'row', alignItems: 'center', paddingTop: 14, paddingBottom: 12,
        paddingHorizontal: 12, borderBottomWidth: StyleSheet.hairlineWidth,
        borderBottomColor: 'rgba(255,255,255,0.08)'},
  back: {width: 40, height: 40, alignItems: 'center', justifyContent: 'center'},
  backTxt: {color: '#e8eaed', fontSize: 20},
  topTtl: {flex: 1, color: '#fff', fontSize: 18, fontWeight: '700', textAlign: 'center'},
  body: {padding: 16, paddingBottom: 40},
  section: {color: '#9aa0a6', fontSize: 13, marginTop: 14, marginBottom: 8,
            marginHorizontal: 4},
  card: {backgroundColor: colors.surfaceElevated, borderRadius: 14, overflow: 'hidden'},
  row: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
        paddingVertical: 15, paddingHorizontal: 16},
  rowTxt: {color: '#e8eaed', fontSize: 16},
  rowTxtSel: {color: '#8db4ff', fontWeight: '700'},
  check: {color: '#8db4ff', fontSize: 16, fontWeight: '700'},
  dim: {color: '#7c8288', fontSize: 14},
  hint: {color: '#7c8288', fontSize: 12.5, lineHeight: 18, marginTop: 10, marginHorizontal: 4},
  free: {borderTopWidth: StyleSheet.hairlineWidth,
         borderTopColor: 'rgba(255,255,255,0.08)',
         paddingVertical: 14, paddingHorizontal: 16},
  freeTtl: {color: colors.success, fontSize: 14, fontWeight: '700', marginBottom: 6},
  freeTxt: {color: '#9aa0a6', fontSize: 13, lineHeight: 19, marginBottom: 4},
  freeBtn: {alignSelf: 'flex-start', marginTop: 8, paddingVertical: 8,
            paddingHorizontal: 14, borderRadius: 18, backgroundColor: colors.primary},
  freeBtnTxt: {color: '#fff', fontSize: 13, fontWeight: '700'},
}));
