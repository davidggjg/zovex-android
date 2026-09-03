// ─────────────────────────────────────────────────────────────────────────────
// פאנל העלאה: בוחרים סרטון מהגלריה, והוא עולה ל"הודעות שמורות" בטלגרם.
//
// שני שלבי התקדמות, כי אלה שתי העברות רשת נפרדות:
//   ① הטלפון → השרת   (נמדד בצד הנייטיבי, בכמה חיבורים במקביל)
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
  startUpload, onUpload, getUploadState, cancelUpload,
  fetchJobStatus, fmtBytes, fmtEta,
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
  // מגבלות שהשרת דיווח עליהן בכניסה: הגודל שטלגרם מרשה לחשבון הזה, והמקום
  // הפנוי בדיסק השרת. הבדיקה נעשית גם בשרת — כאן היא רק חוסכת העלאה שלמה
  // שנועדה להידחות.
  const maxSize = route?.params?.maxSize || 0;
  const freeDisk = route?.params?.freeDisk || 0;

  const [file, setFile] = useState(null);
  const [caption, setCaption] = useState('');
  const [phase, setPhase] = useState('idle');     // idle|sending|telegram|done|error
  const [sent, setSent] = useState(0);
  // הבורר לא תמיד יודע לומר את גודל הקובץ (fileSize חוזר 0 בחלק ממכשירי
  // אנדרואיד). במקרה כזה הגודל האמיתי מגיע עם אירוע ההתקדמות הראשון, ובלעדיו
  // האחוזים היו תקועים על אפס לכל אורך ההעלאה.
  const [total, setTotal] = useState(0);
  // באיזה מסלול ההעלאה רצה וכמה חיבורים פתוחים. בלי זה נאלצנו לבדוק את
  // השרת מבחוץ כדי לדעת אם המקביליות בכלל הופעלה.
  const [link, setLink] = useState({mode: '', workers: 0});
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

  // ההעלאה חיה בצד הנייטיבי ושורדת את המסך הזה, ולכן ההתקדמות מגיעה
  // באירועים. בפתיחת המסך שואבים את המצב הנוכחי: אם העלאה כבר רצה — למשל
  // כשחוזרים לאפליקציה אחרי שיצאנו ממנה — מתחברים אליה במקום להתחיל מאפס.
  useEffect(() => {
    const sub = onUpload(e => {
      if (typeof e.sent === 'number') setSent(e.sent);
      if (e.total > 0) setTotal(e.total);
      if (e.mode) setLink({mode: e.mode, workers: e.workers || 0});
      if (e.type === 'done') {
        if (e.job) { setPhase('telegram'); poll(e.job); }
        else { setPhase('error'); setError('השרת לא החזיר מזהה משימה'); }
      } else if (e.type === 'error') {
        setPhase('error');
        setError(e.error || 'ההעלאה לשרת נכשלה');
      } else {
        setPhase(p => (p === 'idle' || p === 'error' ? 'sending' : p));
      }
    });
    getUploadState().then(st => {
      if (!st) return;
      if (st.running) {
        setPhase('sending');
        setSent(st.sent || 0);
        setTotal(st.total || 0);
        if (st.mode) setLink({mode: st.mode, workers: st.workers || 0});
        // המהירות נמדדת מרגע החיבור מחדש, כי אין לנו את זמן ההתחלה המקורי.
        startedRef.current = Date.now();
      } else if (st.stage === 'done' && st.job) {
        setPhase('telegram');
        poll(st.job);
      }
    }).catch(() => {});
    return () => sub.remove();
  }, [poll]);

  const start = useCallback(async () => {
    if (!file || phase === 'sending' || phase === 'telegram') return;
    setPhase('sending'); setSent(0); setTotal(file.size || 0); setTg(null); setError('');
    setLink({mode: '', workers: 0});
    startedRef.current = Date.now();
    try {
      await startUpload({
        code, uri: file.uri, name: file.name, type: file.type,
        size: file.size, caption,
        duration: file.duration, width: file.width, height: file.height,
      });
    } catch (e) {
      setPhase('error');
      setError(e.message || 'ההעלאה לשרת נכשלה');
    }
  }, [file, phase, code, caption]);

  const busy = phase === 'sending' || phase === 'telegram';
  // הקובץ גדול מהמותר — אין טעם להתחיל. עדיף לומר את זה עכשיו מאשר אחרי
  // שהוא כבר עבר במלואו על רשת סלולרית.
  const tooBig = !!(file && maxSize && file.size > maxSize);
  const noRoom = !!(file && freeDisk && file.size + 536870912 > freeDisk);
  const blocked = tooBig || noRoom;
  const upPct = total ? (100 * sent) / total : 0;
  const upElapsed = (Date.now() - startedRef.current) / 1000;
  const upSpeed = phase === 'sending' && upElapsed > 0.5 ? sent / upElapsed : 0;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => {
            if (busy) {
              Alert.alert(
                'העלאה פעילה',
                'ההעלאה תמשיך גם אם תצא מהאפליקציה, ותוכל לעקוב אחריה בהתראה.',
                [
                  {text: 'הישאר'},
                  {text: 'צא — שימשיך', onPress: () => navigation.goBack()},
                  {text: 'בטל העלאה', style: 'destructive',
                   onPress: () => { cancelUpload(); navigation.goBack(); }},
                ]);
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
            <Text style={styles.stage}>
              ① מהטלפון לשרת
              {link.mode === 'parallel' ? `  ·  ${link.workers} חיבורים במקביל`
                : link.mode === 'single' ? '  ·  חיבור אחד (השרת ישן)' : ''}
            </Text>
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

        {blocked && !busy && (
          <View style={[styles.card, styles.errCard]}>
            <Text style={styles.errTxt}>
              {tooBig
                ? `הקובץ ${fmtBytes(file.size)}, וטלגרם מגביל את החשבון הזה ל-${fmtBytes(maxSize)}.` +
                  (maxSize <= 2147483648 ? ' חשבון Premium מגיע ל-4GB.' : '')
                : `אין מספיק מקום בשרת: פנויים ${fmtBytes(freeDisk)} והקובץ ${fmtBytes(file.size)}.`}
            </Text>
          </View>
        )}

        {!!error && (
          <View style={[styles.card, styles.errCard]}>
            <Text style={styles.errTxt}>{error}</Text>
          </View>
        )}

        <TouchableOpacity
          style={[styles.go, (!file || busy || blocked) && styles.goOff]}
          onPress={start}
          disabled={!file || busy || blocked}>
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
