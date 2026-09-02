// ─────────────────────────────────────────────────────────────────────────────
// פאנל העלאה: בוחרים סרטון מהגלריה, והוא עולה ל"הודעות שמורות" בטלגרם.
//
// שני שלבי התקדמות, כי אלה שתי העברות רשת נפרדות:
//   ① הטלפון → השרת   (נמדד כאן, מאירועי ההתקדמות של ה-XHR)
//   ② השרת → טלגרם    (נמדד בשרת, נשאב בתשאול כל שנייה)
//
// אחרי שלב ② השרת מוחק את הקובץ הזמני — גם אם ההעלאה נכשלה.
// ─────────────────────────────────────────────────────────────────────────────
import React, {useState, useRef, useEffect, useCallback} from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ScrollView,
  ActivityIndicator, TextInput, Alert, NativeModules,
} from 'react-native';

// בורר משלנו ולא react-native-image-picker: זה פתח את גוגל תמונות, שמציג
// פריטים שיושבים בענן ולא במכשיר — וסרט שהורדת יושב ב"הורדות" ובכלל לא מופיע
// שם. VideoPicker פותח את בורר הקבצים של המערכת ומסנן לקבצים מקומיים בלבד.
const {VideoPicker} = NativeModules;
import {
  uploadToServer, fetchJobStatus, fmtBytes, fmtEta,
} from '../api/savedUpload';

const RED = '#e50914';

function Bar({pct, color}) {
  return (
    <View style={styles.barBg}>
      <View style={[styles.barFill, {width: `${Math.max(0, Math.min(100, pct))}%`, backgroundColor: color}]} />
    </View>
  );
}

export default function SavedUploadScreen({route, navigation}) {
  const code = route?.params?.code || '';
  const account = route?.params?.account || '';

  const [file, setFile] = useState(null);
  const [caption, setCaption] = useState('');
  const [phase, setPhase] = useState('idle');     // idle|sending|telegram|done|error
  const [sent, setSent] = useState(0);
  // הבורר לא תמיד יודע לומר את גודל הקובץ (fileSize חוזר 0 בחלק ממכשירי
  // אנדרואיד). במקרה כזה הגודל האמיתי מגיע עם אירוע ההתקדמות הראשון, ובלעדיו
  // האחוזים היו תקועים על אפס לכל אורך ההעלאה.
  const [total, setTotal] = useState(0);
  const [tg, setTg] = useState(null);             // מצב מהשרת
  const [error, setError] = useState('');
  const pollRef = useRef(null);
  const startedRef = useRef(0);

  useEffect(() => () => clearInterval(pollRef.current), []);

  const pick = useCallback(async () => {
    if (!VideoPicker) { setError('בורר הסרטונים אינו זמין בגרסה הזאת'); return; }
    try {
      const a = await VideoPicker.pick();
      if (!a || a.cancelled) return;
      setFile({uri: a.uri, name: a.name || 'video.mp4', size: a.size || 0,
               type: a.type || 'video/mp4', duration: a.duration,
               width: a.width, height: a.height});
      setPhase('idle'); setSent(0); setTotal(a.size || 0); setTg(null); setError('');
    } catch (e) {
      setError(e.message || 'בחירת הסרטון נכשלה');
    }
  }, []);

  const poll = useCallback(job => {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const st = await fetchJobStatus(job);
        setTg(st);
        if (st.stage === 'done') { setPhase('done'); clearInterval(pollRef.current); }
        else if (st.stage === 'error') {
          setPhase('error'); setError(st.error || 'ההעלאה לטלגרם נכשלה');
          clearInterval(pollRef.current);
        }
      } catch (e) {
        // כשל תשאול בודד אינו סוף העולם — ההעלאה בשרת ממשיכה. ממשיכים לנסות.
      }
    }, 1000);
  }, []);

  const start = useCallback(async () => {
    if (!file || phase === 'sending' || phase === 'telegram') return;
    setPhase('sending'); setSent(0); setTotal(file.size || 0); setTg(null); setError('');
    startedRef.current = Date.now();
    try {
      const r = await uploadToServer({
        code, uri: file.uri, name: file.name, type: file.type, caption,
        duration: file.duration, width: file.width, height: file.height,
        onProgress: (s, t) => { setSent(s); if (t > 0) setTotal(t); },
      });
      setPhase('telegram');
      poll(r.job);
    } catch (e) {
      setPhase('error');
      setError(e.message || 'ההעלאה לשרת נכשלה');
    }
  }, [file, phase, code, caption, poll]);

  const busy = phase === 'sending' || phase === 'telegram';
  const upPct = total ? (100 * sent) / total : 0;
  const upElapsed = (Date.now() - startedRef.current) / 1000;
  const upSpeed = phase === 'sending' && upElapsed > 0.5 ? sent / upElapsed : 0;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => {
            if (busy) {
              Alert.alert('העלאה פעילה', 'לצאת עכשיו יבטל את המעקב. ההעלאה בשרת תמשיך.',
                [{text: 'הישאר'}, {text: 'צא', onPress: () => navigation.goBack()}]);
              return;
            }
            navigation.goBack();
          }}
          style={styles.back}>
          <Text style={styles.backTxt}>✕</Text>
        </TouchableOpacity>
        <View>
          <Text style={styles.title}>העלאה להודעות שמורות</Text>
          {!!account && <Text style={styles.sub}>{account}</Text>}
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.body}>
        <TouchableOpacity style={styles.pickBtn} onPress={pick} disabled={busy}>
          <Text style={styles.pickTxt}>
            {file ? '🎬 בחר סרטון אחר' : '🎬 בחר סרטון מהמכשיר'}
          </Text>
        </TouchableOpacity>

        {!!file && (
          <View style={styles.card}>
            <Text style={styles.fileName} numberOfLines={2}>{file.name}</Text>
            <Text style={styles.meta}>
              {total ? fmtBytes(total) : '—'}
              {file.duration ? ` · ${Math.round(file.duration)} שנ׳` : ''}
            </Text>
          </View>
        )}

        {!!file && (
          <TextInput
            value={caption}
            onChangeText={setCaption}
            editable={!busy}
            placeholder="כיתוב (לא חובה)"
            placeholderTextColor="#666"
            style={styles.input}
          />
        )}

        {/* ① טלפון → שרת */}
        {(phase === 'sending' || phase === 'telegram' || phase === 'done') && (
          <View style={styles.card}>
            <Text style={styles.stage}>① מהטלפון לשרת</Text>
            <Bar pct={phase === 'sending' ? upPct : 100} color="#3ba55d" />
            <Text style={styles.meta}>
              {phase === 'sending'
                ? `${upPct.toFixed(1)}% · ${fmtBytes(sent)} מתוך ${total ? fmtBytes(total) : '—'}` +
                  (upSpeed && total ? ` · ${fmtBytes(upSpeed)}/שנ׳ · נותרו ${fmtEta((total - sent) / upSpeed)}` : '')
                : '✓ הושלם'}
            </Text>
          </View>
        )}

        {/* ② שרת → טלגרם */}
        {(phase === 'telegram' || phase === 'done' || (phase === 'error' && tg)) && (
          <View style={styles.card}>
            <Text style={styles.stage}>② מהשרת לטלגרם</Text>
            <Bar pct={tg?.pct || 0} color={phase === 'error' ? '#c0392b' : RED} />
            <Text style={styles.meta}>
              {tg?.stage === 'queued' ? 'ממתין לתור…'
                : tg?.stage === 'done' ? '✓ הועלה להודעות שמורות'
                : tg?.stage === 'error' ? `✗ ${tg.error}`
                : `${(tg?.pct || 0).toFixed(1)}% · ${fmtBytes(tg?.sent || 0)} מתוך ${fmtBytes(tg?.total || 0)}` +
                  (tg?.speed ? ` · ${fmtBytes(tg.speed)}/שנ׳ · נותרו ${fmtEta(tg.eta)}` : '')}
            </Text>
          </View>
        )}

        {phase === 'done' && (
          <View style={[styles.card, styles.okCard]}>
            <Text style={styles.okTxt}>✅ הסרטון בהודעות השמורות</Text>
            <Text style={styles.meta}>הקובץ הזמני נמחק מהשרת.</Text>
          </View>
        )}

        {!!error && (
          <View style={[styles.card, styles.errCard]}>
            <Text style={styles.errTxt}>{error}</Text>
          </View>
        )}

        <TouchableOpacity
          style={[styles.go, (!file || busy) && styles.goOff]}
          onPress={start}
          disabled={!file || busy}>
          {busy ? <ActivityIndicator color="#fff" />
                : <Text style={styles.goTxt}>{phase === 'done' ? 'העלה עוד סרטון' : 'העלה'}</Text>}
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0a0a0a'},
  header: {flexDirection: 'row-reverse', alignItems: 'center', gap: 12,
           padding: 16, borderBottomWidth: 1, borderBottomColor: '#1c1c1e'},
  back: {width: 36, height: 36, borderRadius: 18, backgroundColor: '#1c1c1e',
         alignItems: 'center', justifyContent: 'center'},
  backTxt: {color: '#fff', fontSize: 15, fontWeight: '700'},
  title: {color: '#fff', fontSize: 17, fontWeight: '800', textAlign: 'right'},
  sub: {color: '#888', fontSize: 12, textAlign: 'right', marginTop: 2},
  body: {padding: 16, paddingBottom: 40, gap: 14},
  pickBtn: {backgroundColor: '#1c1c1e', borderRadius: 14, paddingVertical: 18,
            alignItems: 'center', borderWidth: 1, borderColor: '#2c2c2e'},
  pickTxt: {color: '#fff', fontSize: 15, fontWeight: '700'},
  card: {backgroundColor: '#141416', borderRadius: 14, padding: 14,
         borderWidth: 1, borderColor: '#232326', gap: 8},
  fileName: {color: '#fff', fontSize: 14, fontWeight: '700', textAlign: 'right'},
  meta: {color: '#9a9aa2', fontSize: 12, textAlign: 'right'},
  stage: {color: '#fff', fontSize: 13, fontWeight: '800', textAlign: 'right'},
  input: {backgroundColor: '#141416', borderRadius: 12, borderWidth: 1,
          borderColor: '#232326', color: '#fff', paddingHorizontal: 14,
          paddingVertical: 12, textAlign: 'right', fontSize: 14},
  barBg: {height: 8, borderRadius: 4, backgroundColor: '#242428', overflow: 'hidden'},
  barFill: {height: '100%', borderRadius: 4},
  okCard: {borderColor: '#2b5d3a', backgroundColor: '#12301d'},
  okTxt: {color: '#7ee2a0', fontSize: 14, fontWeight: '800', textAlign: 'right'},
  errCard: {borderColor: '#5d2b2b', backgroundColor: '#301212'},
  errTxt: {color: '#ff9b9b', fontSize: 13, textAlign: 'right'},
  go: {backgroundColor: RED, borderRadius: 14, paddingVertical: 16,
       alignItems: 'center', marginTop: 4},
  goOff: {backgroundColor: '#3a2023'},
  goTxt: {color: '#fff', fontSize: 16, fontWeight: '800'},
});
