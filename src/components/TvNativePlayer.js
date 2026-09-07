import React, {useEffect, useRef, useState} from 'react';
import {View, StyleSheet, ActivityIndicator, Text} from 'react-native';
import Video from 'react-native-video';

// נגן נייטיב (ExoPlayer) לטלוויזיה. בטלוויזיות ה-WebView חלש וקורס בפענוח
// 1080p; ExoPlayer משתמש בשבב הפענוח של הטלוויזיה, מנגן חלק, ותומך בשלט
// (D-pad) דרך פקדי הבקרה המובנים. משמש רק ל-mp4/HLS ישיר (לא ל-iframe).
export default function TvNativePlayer({
  src,
  isLive,
  startTime = 0,
  onProgress,
  onEnd,
  onError,
  // מציג על המסך מה ExoPlayer באמת ראה: אילו רצועות, מה נבחר, ומה נכשל.
  // נדלק רק במסלול תיקון-הקול — שם אנחנו עדיין לא יודעים למה זה לא עובד,
  // ובלי המידע הזה כל תיקון הוא ניחוש.
  debug = false,
}) {
  const ref = useRef(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  // מתחיל עם טקסט ולא ריק בכוונה: אם הנגן נתקע *לפני* onLoad, שום דבר לא
  // היה מוצג — וזה בדיוק המקרה שאנחנו מנסים לתפוס. עכשיו תמיד יש מה לראות.
  const [diag, setDiag] = useState(debug ? 'פותח את הקובץ…' : '');
  // שידור חי/HLS מול קובץ שלם — שני מקרים עם צרכי באפר הפוכים לגמרי.
  const isHls = isLive || /\.m3u8|Manifest\.ism/i.test(src || '');

  // אם אחרי 15 שניות עוד לא נפתח כלום — אומרים את זה, במקום להשאיר
  // "פותח את הקובץ…" שנראה כמו טעינה תמימה.
  useEffect(() => {
    if (!debug) return;
    const t = setTimeout(() => {
      setDiag(d => (d.startsWith('פותח') ? 'לא נפתח תוך 15 שניות — הנגן לא ' +
        'הגיע ל-onLoad בכלל.\n' + String(src || '').slice(0, 120) : d));
    }, 15000);
    return () => clearTimeout(t);
  }, [debug, src]);

  return (
    <View style={styles.wrap}>
      <Video
        ref={ref}
        // type מפורש: הכתובות שלנו עוברות דרך ה-relay ולא תמיד נגמרות בסיומת
        // שממנה ExoPlayer מסיק את הפורמט. בלי זה הוא עלול לנסות לנגן playlist
        // כאילו היה קובץ רגיל ולהיתקע.
        source={{
          uri: src,
          type: isHls ? 'm3u8' : undefined,
          // הממסר איטי: נמדד 0.7–3s ל-playlist ועוד 1.6–3.7s למקטע של 6 שניות.
          // עם ברירת המחדל אין מרווח ביטחון וכל עיכוב מרוקן את הבאפר — זה מה
          // שנראה כ"מסתובב הרבה". כמה ניסיונות חוזרים מונעים נפילה על תקלה אחת.
          minLoadRetryCount: 6,
        }}
        // הבאפר המוגדל שייך ל-HLS/שידור חי בלבד. בגרסה קודמת הוא הוחל על כל
        // ניגון נייטיבי, וזה שבר את הסרטים: 90 שניות של 1080p הן עשרות MB
        // שהטלוויזיה צריכה להחזיק ולמלא לפני שמתחילה — ולכן "שידורים חיים
        // עובדים אבל תכנים מסתובבים". לקובץ שלם משאירים את ברירת המחדל של
        // ExoPlayer, שמכוילת בדיוק למקרה הזה.
        bufferConfig={isHls ? {
          minBufferMs: 15000,
          maxBufferMs: 50000,
          bufferForPlaybackMs: 2500,
          bufferForPlaybackAfterRebufferMs: 5000,
        } : undefined}
        style={StyleSheet.absoluteFill}
        controls
        paused={false}
        resizeMode="contain"
        // עדכון התקדמות כל 3 שניות — מספיק לשמירת "המשך צפייה" בלי עומס.
        progressUpdateInterval={3000}
        onLoad={d => {
          setReady(true);
          if (debug) {
            const a = (d?.audioTracks || []).map(
              t => `${t.index}:${t.type || '?'}${t.selected ? '*' : ''}`).join(' ');
            const v = (d?.videoTracks || []).map(
              t => `${t.index}:${t.codecs || '?'}${t.width ? ` ${t.width}x${t.height}` : ''}${t.selected ? '*' : ''}`).join(' ');
            setDiag(`אודיו[${a || 'אין'}]  וידאו[${v || 'אין'}]  ` +
                    `משך ${Math.round(d?.duration || 0)}ש`);
          }
          if (!isLive && startTime > 1 && ref.current) {
            try { ref.current.seek(startTime); } catch (_) {}
          }
        }}
        onProgress={p => {
          if (onProgress) {
            const dur = p.seekableDuration || p.playableDuration || 0;
            onProgress(p.currentTime || 0, dur);
          }
        }}
        onEnd={() => { if (onEnd) onEnd(); }}
        onError={e => {
          setFailed(true);
          if (debug) {
            const x = e?.error || {};
            setDiag(d => `${d}\nשגיאה: ${x.errorCode || ''} ` +
              `${x.errorString || x.errorException || JSON.stringify(x).slice(0, 160)}`);
          }
          if (onError) onError(e);
        }}
      />
      {!ready && !failed && (
        <ActivityIndicator style={styles.center} color="#e50914" size="large" />
      )}
      {failed && (
        <View style={styles.center}>
          <Text style={styles.err}>לא ניתן לנגן את הווידאו</Text>
        </View>
      )}
      {debug && !!diag && (
        <View style={styles.diag} pointerEvents="none">
          <Text style={styles.diagTxt}>{diag}</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {flex: 1, backgroundColor: '#000'},
  center: {position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, justifyContent: 'center', alignItems: 'center'},
  err: {color: '#ddd', fontSize: 16},
  diag: {position: 'absolute', top: 0, left: 0, right: 0,
    backgroundColor: 'rgba(0,0,0,0.75)', paddingHorizontal: 8, paddingVertical: 6},
  diagTxt: {color: '#9ad', fontSize: 11, textAlign: 'left'},
});
