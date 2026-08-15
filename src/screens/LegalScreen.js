import React, {useState} from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet, Linking, StatusBar,
} from 'react-native';
import {LEGAL_DOCS, UPDATED} from '../config/legal';
import {TELEGRAM_URL, DISCORD_URL} from '../config/links';

// מסך מידע ותנאים. הטקסט מקומי ולא נמשך מהרשת, כדי שהוא ייפתח גם בלי
// חיבור — וגם כדי שחנות האפליקציות תראה מדיניות פרטיות זמינה תמיד.
export default function LegalScreen({route, navigation}) {
  const initial = route?.params?.doc;
  const startIndex = Math.max(0, LEGAL_DOCS.findIndex(d => d.key === initial));
  const [index, setIndex] = useState(startIndex);
  const doc = LEGAL_DOCS[index];

  const open = url => Linking.openURL(url).catch(() => {});

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor="#0b0b0b" />
      <View style={styles.topBar}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backTxt}>✕</Text>
        </TouchableOpacity>
        <Text style={styles.topTitle}>מידע ותנאים</Text>
        <View style={styles.backBtn} />
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.tabs}>
        {LEGAL_DOCS.map((d, i) => (
          <TouchableOpacity
            key={d.key}
            onPress={() => setIndex(i)}
            style={[styles.tab, i === index && styles.tabOn]}
            activeOpacity={0.8}>
            <Text style={[styles.tabTxt, i === index && styles.tabTxtOn]}>{d.tab}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <ScrollView contentContainerStyle={styles.body} showsVerticalScrollIndicator={false}>
        <Text style={styles.h1}>{doc.title}</Text>
        <Text style={styles.updated}>עודכן: {UPDATED}</Text>

        {doc.sections.map(([heading, paras]) => (
          <View key={heading} style={styles.section}>
            <Text style={styles.h2}>{heading}</Text>
            {paras.map((p, i) => (
              <Text key={i} style={styles.p}>{p}</Text>
            ))}
          </View>
        ))}

        <View style={styles.footer}>
          <TouchableOpacity onPress={() => open(DISCORD_URL)}>
            <Text style={[styles.link, {color: '#7c85f5'}]}>דיסקורד</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => open(TELEGRAM_URL)}>
            <Text style={[styles.link, {color: '#5b9bd5'}]}>טלגרם</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0b0b0b'},
  topBar: {
    flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 12, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: '#1c1c1c',
  },
  backBtn: {width: 38, height: 38, alignItems: 'center', justifyContent: 'center'},
  backTxt: {color: '#fff', fontSize: 20},
  topTitle: {color: '#fff', fontSize: 16, fontWeight: '800'},

  tabs: {flexDirection: 'row-reverse', paddingHorizontal: 12, paddingVertical: 12, gap: 8},
  tab: {
    paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, marginLeft: 8,
    backgroundColor: '#1a1a1a', borderWidth: 1, borderColor: '#2a2a2a',
  },
  tabOn: {backgroundColor: '#e50914', borderColor: '#e50914'},
  tabTxt: {color: '#aaa', fontSize: 13, fontWeight: '700'},
  tabTxtOn: {color: '#fff'},

  body: {paddingHorizontal: 18, paddingBottom: 50},
  h1: {color: '#fff', fontSize: 22, fontWeight: '900', textAlign: 'right', marginTop: 6},
  updated: {color: '#777', fontSize: 12, textAlign: 'right', marginTop: 4, marginBottom: 20},
  section: {marginBottom: 20},
  h2: {color: '#fff', fontSize: 15, fontWeight: '800', textAlign: 'right', marginBottom: 6},
  p: {color: '#ccc', fontSize: 14, lineHeight: 22, textAlign: 'right', marginBottom: 7},

  footer: {
    flexDirection: 'row-reverse', gap: 16, borderTopWidth: 1, borderTopColor: '#222',
    paddingTop: 16, marginTop: 10,
  },
  link: {fontSize: 14, fontWeight: '700', marginLeft: 16},
});
