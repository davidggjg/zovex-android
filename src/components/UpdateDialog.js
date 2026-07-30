// ─────────────────────────────────────────────────────────────────────────────
// ZOVEX · דיאלוג עדכון. בהפעלה בודק מול השרת (/app/version) מהי הגרסה האחרונה
// והמינימלית. אם הגרסה של המשתמש נמוכה מהמינימלית → דיאלוג חוסם (חובה לעדכן).
// אם נמוכה מהאחרונה בלבד → הצעה לעדכן שאפשר לסגור. הקישור מגיע מהשרת.
// ─────────────────────────────────────────────────────────────────────────────
import React, {useEffect, useState} from 'react';
import {View, Text, Modal, TouchableOpacity, StyleSheet, Linking} from 'react-native';
import {fetchAppVersion, cmpVersion, APP_VERSION} from '../api/movies';

export default function UpdateDialog() {
  const [state, setState] = useState(null); // {forced, url, notes, latest}
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      const v = await fetchAppVersion();
      if (!alive || !v) return;
      const belowMin = cmpVersion(APP_VERSION, v.min) < 0;
      const belowLatest = cmpVersion(APP_VERSION, v.latest) < 0;
      if (belowMin || belowLatest) {
        setState({
          forced: belowMin,
          url: v.url || 'https://github.com/davidggjg/zovex-android/releases/latest',
          notes: v.notes || '',
          latest: v.latest || '',
        });
      }
    })();
    return () => { alive = false; };
  }, []);

  if (!state) return null;
  if (dismissed && !state.forced) return null;

  const open = () => Linking.openURL(state.url).catch(() => {});

  return (
    <Modal visible transparent animationType="fade" onRequestClose={() => {
      if (!state.forced) setDismissed(true);
    }}>
      <View style={styles.overlay}>
        <View style={styles.card}>
          <Text style={styles.emoji}>🚀</Text>
          <Text style={styles.title}>
            {state.forced ? 'עדכון נדרש' : 'גרסה חדשה זמינה'}
          </Text>
          <Text style={styles.body}>
            {state.notes ||
              (state.forced
                ? 'הגרסה שלכם אינה נתמכת יותר. יש לעדכן כדי להמשיך להשתמש באפליקציה.'
                : 'שדרגנו את האפליקציה! מומלץ לעדכן לגרסה האחרונה.')}
          </Text>
          {state.latest ? (
            <Text style={styles.ver}>גרסה {state.latest}</Text>
          ) : null}
          <TouchableOpacity style={styles.updateBtn} onPress={open} activeOpacity={0.85}>
            <Text style={styles.updateTxt}>⬇️ עדכן עכשיו</Text>
          </TouchableOpacity>
          {!state.forced && (
            <TouchableOpacity style={styles.laterBtn} onPress={() => setDismissed(true)}>
              <Text style={styles.laterTxt}>אחר כך</Text>
            </TouchableOpacity>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {flex: 1, backgroundColor: 'rgba(0,0,0,0.85)', justifyContent: 'center', alignItems: 'center', paddingHorizontal: 30},
  card: {backgroundColor: '#161616', borderRadius: 20, padding: 26, alignItems: 'center', width: '100%', borderWidth: 1, borderColor: '#2a2a2a'},
  emoji: {fontSize: 46, marginBottom: 8},
  title: {color: '#fff', fontSize: 22, fontWeight: '900', marginBottom: 10, textAlign: 'center'},
  body: {color: '#bbb', fontSize: 15, textAlign: 'center', lineHeight: 22, marginBottom: 8},
  ver: {color: '#666', fontSize: 13, marginBottom: 16},
  updateBtn: {backgroundColor: '#e50914', borderRadius: 14, paddingVertical: 14, paddingHorizontal: 40, marginTop: 8, width: '100%', alignItems: 'center'},
  updateTxt: {color: '#fff', fontSize: 16, fontWeight: '800'},
  laterBtn: {paddingVertical: 12, marginTop: 4},
  laterTxt: {color: '#777', fontSize: 14},
});
