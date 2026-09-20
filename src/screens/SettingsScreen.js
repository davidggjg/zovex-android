import React, {useState} from 'react';
import {View, Text, TouchableOpacity, StyleSheet, ScrollView, StatusBar} from 'react-native';
import {LANGS, getLanguage, setLanguage, t} from '../i18n';
import TvFocusable from '../components/TvFocusable';
import {APP_VERSION} from '../api/movies';

// מסך הגדרות. כרגע שפה בלבד — נבנה כמסך ולא כחלון קופץ כדי שיהיה מקום
// להגדרות נוספות בלי לשנות מבנה.
export default function SettingsScreen({navigation}) {
  const [lang, setLang] = useState(getLanguage());

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
        </View>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: {flex: 1, backgroundColor: '#0f1115'},
  top: {flexDirection: 'row', alignItems: 'center', paddingTop: 14, paddingBottom: 12,
        paddingHorizontal: 12, borderBottomWidth: StyleSheet.hairlineWidth,
        borderBottomColor: 'rgba(255,255,255,0.08)'},
  back: {width: 40, height: 40, alignItems: 'center', justifyContent: 'center'},
  backTxt: {color: '#e8eaed', fontSize: 20},
  topTtl: {flex: 1, color: '#fff', fontSize: 18, fontWeight: '700', textAlign: 'center'},
  body: {padding: 16, paddingBottom: 40},
  section: {color: '#9aa0a6', fontSize: 13, marginTop: 14, marginBottom: 8,
            marginHorizontal: 4},
  card: {backgroundColor: '#15181f', borderRadius: 14, overflow: 'hidden'},
  row: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
        paddingVertical: 15, paddingHorizontal: 16},
  rowTxt: {color: '#e8eaed', fontSize: 16},
  rowTxtSel: {color: '#8db4ff', fontWeight: '700'},
  check: {color: '#8db4ff', fontSize: 16, fontWeight: '700'},
  dim: {color: '#7c8288', fontSize: 14},
  hint: {color: '#7c8288', fontSize: 12.5, lineHeight: 18, marginTop: 10, marginHorizontal: 4},
});
