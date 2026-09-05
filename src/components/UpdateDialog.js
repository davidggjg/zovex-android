// ─────────────────────────────────────────────────────────────────────────────
// ZOVEX · דיאלוג עדכון. בהפעלה בודק מול השרת (/app/version) מהי הגרסה האחרונה
// והמינימלית. אם הגרסה של המשתמש נמוכה מהמינימלית → דיאלוג חוסם (חובה לעדכן).
// אם נמוכה מהאחרונה בלבד → הצעה לעדכן שאפשר לסגור.
//
// העדכון מתבצע *בתוך האפליקציה*: מורידים את ה-APK לתיקיית המטמון עם אחוזי
// התקדמות, ואז פותחים את מתקין המערכת על הקובץ. המשתמש רק מאשר "התקן" — בלי
// דפדפן ובלי גיטהאב. אם ההורדה/ההתקנה נכשלת (למשל רום נעול שחוסם התקנות),
// נופלים חזרה לפתיחת הקישור בדפדפן כדי שתמיד תהיה דרך לעדכן.
// ─────────────────────────────────────────────────────────────────────────────
import React, {useEffect, useState} from 'react';
import TvFocusable from '../components/TvFocusable';
import {
  View,
  Text,
  Modal,
  TouchableOpacity,
  StyleSheet,
  Linking,
  NativeModules,
} from 'react-native';
import RNFS from 'react-native-fs';
import {fetchAppVersion, cmpVersion, APP_VERSION} from '../api/movies';

const {ApkInstaller} = NativeModules;

// קובץ העדכון מוגש מהשרת שלנו (/app/apk) — המשתמש לעולם לא נחשף למקור החיצוני
// שממנו הקובץ מגיע. השרת מחזיר שדה apk; אם משום מה אין — נופלים לברירת המחדל
// של הדומיין שלנו, אף פעם לא לקישור חיצוני.
const APK_FALLBACK = 'https://zovex.duckdns.org/app/apk';

function directApkUrl(v) {
  if (v && v.apk) return v.apk;
  const u = (v && v.url) || '';
  if (/\.apk$/i.test(u)) return u;
  return APK_FALLBACK;
}

export default function UpdateDialog() {
  const [state, setState] = useState(null); // {forced, url, notes, latest, apk}
  const [dismissed, setDismissed] = useState(false);
  const [pct, setPct] = useState(-1); // -1 = לא מוריד
  const [err, setErr] = useState('');

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
          url: directApkUrl(v),   // גם הנפילה-לאחור נשארת בדומיין שלנו
          apk: directApkUrl(v),
          notes: v.notes || '',
          latest: v.latest || '',
        });
      }
    })();
    return () => { alive = false; };
  }, []);

  if (!state) return null;
  if (dismissed && !state.forced) return null;

  const openInBrowser = () => Linking.openURL(state.url).catch(() => {});

  const startUpdate = async () => {
    setErr('');
    // בלי המודול המקורי (בנייה ישנה) — נופלים לדפדפן.
    if (!ApkInstaller) return openInBrowser();
    try {
      // אנדרואיד 8+: צריך אישור חד-פעמי "התקנת אפליקציות לא ידועות".
      const allowed = await ApkInstaller.canInstall();
      if (!allowed) {
        setErr('כדי לעדכן מתוך האפליקציה — אשרו "התקנת אפליקציות לא ידועות", ואז לחצו שוב על עדכן.');
        await ApkInstaller.openInstallSettings().catch(() => {});
        return;
      }
      const dest = `${RNFS.CachesDirectoryPath}/zovex-update.apk`;
      if (await RNFS.exists(dest)) {
        await RNFS.unlink(dest).catch(() => {});
      }
      setPct(0);
      const task = RNFS.downloadFile({
        fromUrl: state.apk,
        toFile: dest,
        // GitHub מפנה ל-CDN — react-native-fs עוקב אחרי ההפניה בעצמו.
        progressDivider: 1,
        begin: () => setPct(0),
        progress: r => {
          if (r.contentLength > 0) {
            setPct(Math.round((r.bytesWritten / r.contentLength) * 100));
          }
        },
      });
      const res = await task.promise;
      if (res.statusCode !== 200) throw new Error('HTTP ' + res.statusCode);
      const st = await RNFS.stat(dest);
      // שפיות: APK אמיתי הוא כמה מגה. קובץ זעיר = דף שגיאה שהורד בטעות.
      if (Number(st.size) < 1000000) throw new Error('הקובץ שהתקבל אינו תקין');
      setPct(100);
      await ApkInstaller.install(dest);
      // המתקין נפתח — משאירים את המסך כמו שהוא; אחרי ההתקנה האפליקציה תופעל מחדש.
    } catch (e) {
      setPct(-1);
      setErr('העדכון האוטומטי נכשל. פותח את הדף להורדה ידנית…');
      setTimeout(openInBrowser, 1200);
    }
  };

  const downloading = pct >= 0;

  return (
    <Modal visible transparent animationType="fade" onRequestClose={() => {
      if (!state.forced && !downloading) setDismissed(true);
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

          {downloading ? (
            <View style={styles.progWrap}>
              <View style={styles.progTrack}>
                <View style={[styles.progFill, {width: `${Math.max(pct, 2)}%`}]} />
              </View>
              <Text style={styles.progTxt}>
                {pct >= 100 ? 'מתקין…' : `מוריד עדכון… ${pct}%`}
              </Text>
            </View>
          ) : (
            <TvFocusable style={styles.updateBtn} onPress={startUpdate} activeOpacity={0.85}>
              <Text style={styles.updateTxt}>⬇️ עדכן עכשיו</Text>
            </TvFocusable>
          )}

          {err ? <Text style={styles.err}>{err}</Text> : null}

          {!state.forced && !downloading && (
            <TvFocusable style={styles.laterBtn} onPress={() => setDismissed(true)}>
              <Text style={styles.laterTxt}>אחר כך</Text>
            </TvFocusable>
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
  progWrap: {width: '100%', marginTop: 10},
  progTrack: {width: '100%', height: 10, borderRadius: 6, backgroundColor: '#2a2a2a', overflow: 'hidden'},
  progFill: {height: '100%', backgroundColor: '#e50914', borderRadius: 6},
  progTxt: {color: '#ddd', fontSize: 14, textAlign: 'center', marginTop: 10, fontWeight: '700'},
  err: {color: '#ff8a8a', fontSize: 13, textAlign: 'center', marginTop: 12, lineHeight: 19},
});
