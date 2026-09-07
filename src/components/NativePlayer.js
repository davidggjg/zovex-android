import React, {useCallback, useEffect, useRef, useState} from 'react';
import {
  View, Text, StyleSheet, ActivityIndicator, TouchableOpacity,
  PanResponder, Pressable,
} from 'react-native';
import Video from 'react-native-video';

// נגן נייטיב עם הפקדים **שלנו**.
//
// למה הוא קיים בכלל: ה-WebView לא מפענח ec-3 (Dolby Digital Plus) בשום
// מקרה — אנדרואיד לא מחייב יצרנים לכלול מפענח Dolby, וה-WebView מוותר על
// רצועת הקול בשקט. הנגן הנייטיב כן, כי האפליקציה מביאה איתה את מפענחי
// ה-FFmpeg של Media3.
//
// אבל הפקדים המובנים של Media3 נראים כמו נגן אחר לגמרי, ובאמצע סרט זה
// מרגיש כאילו האפליקציה החליפה את עצמה. לכן כאן: אותו ExoPlayer, עם
// הממשק של הנגן הרגיל שלנו — אותו ורוד (#e91e8c), אותה פריסה, אותה
// התנהגות של הסתרה אוטומטית.
//
// בטלוויזיה ממשיכים עם TvNativePlayer והפקדים המובנים, כי הם אלה
// שעובדים עם ה-D-pad של השלט.

const ACCENT = '#e91e8c';
const HIDE_AFTER = 3500;

const fmt = s => {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const x = s % 60;
  const p = n => (n < 10 ? '0' + n : String(n));
  return h > 0 ? `${h}:${p(m)}:${p(x)}` : `${m}:${p(x)}`;
};

export default function NativePlayer({
  src,
  title,
  subtitle,
  startTime = 0,
  hasNext = false,
  nextLabel = '',
  onClose,
  onProgress,
  onEnd,
  onError,
  onNext,
  onPlayingChange,
  debug = false,
}) {
  const ref = useRef(null);
  const [paused, setPaused] = useState(false);
  const [ready, setReady] = useState(false);
  const [pos, setPos] = useState(0);
  const [dur, setDur] = useState(0);
  const [shown, setShown] = useState(true);
  const [barW, setBarW] = useState(1);
  const [diag, setDiag] = useState(debug ? 'פותח את הקובץ…' : '');
  // בזמן גרירה לא נותנים ל-onProgress לדרוס את המיקום שהאצבע קובעת,
  // אחרת הנקודה קופצת אחורה כל שלוש שניות תוך כדי הגרירה.
  const dragging = useRef(false);
  const hideTimer = useRef(null);
  const posRef = useRef(0);
  const durRef = useRef(0);
  const barWRef = useRef(1);

  const poke = useCallback(() => {
    setShown(true);
    if (hideTimer.current) clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setShown(false), HIDE_AFTER);
  }, []);

  useEffect(() => {
    poke();
    return () => { if (hideTimer.current) clearTimeout(hideTimer.current); };
  }, [poke]);

  useEffect(() => { onPlayingChange && onPlayingChange(!paused); }, [paused, onPlayingChange]);

  useEffect(() => {
    if (!debug) return;
    const t = setTimeout(() => {
      setDiag(d => (d.startsWith('פותח')
        ? 'לא נפתח תוך 15 שניות.\n' + String(src || '').slice(0, 120) : d));
    }, 15000);
    return () => clearTimeout(t);
  }, [debug, src]);

  const seekTo = t => {
    const v = Math.max(0, Math.min(t, durRef.current || t));
    posRef.current = v;
    setPos(v);
    try { ref.current && ref.current.seek(v); } catch (_) {}
  };

  const skip = d => { seekTo(posRef.current + d); poke(); };

  // סרגל ההתקדמות. PanResponder ולא Slider חיצוני — אין ספריית slider
  // בפרויקט, והוספת תלות בשביל פס אחד לא מוצדקת.
  const pan = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: e => {
        dragging.current = true;
        const f = Math.max(0, Math.min(1, e.nativeEvent.locationX / barWRef.current));
        setPos(f * (durRef.current || 0));
      },
      onPanResponderMove: e => {
        const f = Math.max(0, Math.min(1, e.nativeEvent.locationX / barWRef.current));
        setPos(f * (durRef.current || 0));
      },
      onPanResponderRelease: e => {
        const f = Math.max(0, Math.min(1, e.nativeEvent.locationX / barWRef.current));
        dragging.current = false;
        seekTo(f * (durRef.current || 0));
        poke();
      },
      onPanResponderTerminate: () => { dragging.current = false; },
    }),
  ).current;

  const frac = dur > 0 ? Math.max(0, Math.min(1, pos / dur)) : 0;

  return (
    <View style={styles.wrap}>
      <Video
        ref={ref}
        source={{uri: src, minLoadRetryCount: 6}}
        style={StyleSheet.absoluteFill}
        controls={false}
        paused={paused}
        resizeMode="contain"
        progressUpdateInterval={500}
        onLoad={d => {
          setReady(true);
          const dd = d?.duration || 0;
          durRef.current = dd;
          setDur(dd);
          if (debug) {
            const a = (d?.audioTracks || []).map(
              t => `${t.index}:${t.type || '?'}${t.selected ? '*' : ''}`).join(' ');
            const v = (d?.videoTracks || []).map(
              t => `${t.index}:${t.codecs || '?'}${t.selected ? '*' : ''}`).join(' ');
            setDiag(`אודיו[${a || 'אין'}] וידאו[${v || 'אין'}] ${Math.round(dd)}ש`);
          }
          if (startTime > 1) seekTo(startTime);
        }}
        onProgress={p => {
          if (!dragging.current) {
            posRef.current = p.currentTime || 0;
            setPos(posRef.current);
          }
          const d2 = p.seekableDuration || durRef.current || 0;
          if (d2 && d2 !== durRef.current) { durRef.current = d2; setDur(d2); }
          onProgress && onProgress(p.currentTime || 0, d2);
        }}
        onEnd={() => onEnd && onEnd()}
        onError={e => {
          if (debug) {
            const x = e?.error || {};
            setDiag(d => `${d}\nשגיאה: ${x.errorCode || ''} ` +
              `${x.errorString || x.errorException || JSON.stringify(x).slice(0, 160)}`);
          }
          onError && onError(e);
        }}
      />

      {/* שכבת הקשה: מציגה ומסתירה את הפקדים */}
      <Pressable style={StyleSheet.absoluteFill}
        onPress={() => (shown ? setShown(false) : poke())} />

      {!ready && <ActivityIndicator style={styles.center} color={ACCENT} size="large" />}

      {shown && (
        <>
          <View style={styles.topbar} pointerEvents="box-none">
            <TouchableOpacity style={styles.xbtn} onPress={onClose} hitSlop={12}>
              <Text style={styles.xtxt}>✕</Text>
            </TouchableOpacity>
            <View style={styles.ttl} pointerEvents="none">
              <Text style={styles.ttlMain} numberOfLines={1}>{title || ''}</Text>
              {!!subtitle && <Text style={styles.ttlSub} numberOfLines={1}>{subtitle}</Text>}
            </View>
            <View style={styles.xbtn} />
          </View>

          <View style={styles.mid} pointerEvents="box-none">
            <TouchableOpacity style={styles.cbtn} onPress={() => skip(-10)}>
              <Text style={styles.cglyph}>↺</Text><Text style={styles.cnum}>10</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.cbtn}
              onPress={() => { setPaused(p => !p); poke(); }}>
              <Text style={styles.play}>{paused ? '▶' : '❚❚'}</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.cbtn} onPress={() => skip(10)}>
              <Text style={styles.cglyph}>↻</Text><Text style={styles.cnum}>10</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.bottombar} pointerEvents="box-none">
            <View style={styles.progwrap} {...pan.panHandlers}
              onLayout={e => { barWRef.current = e.nativeEvent.layout.width || 1;
                               setBarW(barWRef.current); }}>
              <View style={styles.track}>
                <View style={[styles.fill, {width: `${frac * 100}%`}]} />
                <View style={[styles.dot, {left: Math.max(0, frac * barW - 6.5)}]} />
              </View>
            </View>
            <View style={styles.brow}>
              <Text style={styles.time}>{fmt(pos)} / {fmt(dur)}</Text>
              {hasNext && (
                <TouchableOpacity style={styles.nextBtn} onPress={onNext}>
                  <Text style={styles.nextTxt}>
                    {nextLabel ? `הבא: ${nextLabel}` : 'הפרק הבא ▶'}
                  </Text>
                </TouchableOpacity>
              )}
            </View>
          </View>
        </>
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
  center: {position: 'absolute', top: 0, bottom: 0, left: 0, right: 0,
    justifyContent: 'center', alignItems: 'center'},

  topbar: {position: 'absolute', top: 0, left: 0, right: 0, paddingHorizontal: 16,
    paddingTop: 14, paddingBottom: 34, flexDirection: 'row-reverse',
    alignItems: 'flex-start', backgroundColor: 'rgba(0,0,0,0.55)'},
  xbtn: {width: 34, alignItems: 'center', justifyContent: 'center'},
  xtxt: {color: '#fff', fontSize: 24, lineHeight: 26},
  ttl: {flex: 1, alignItems: 'center', paddingTop: 2},
  ttlMain: {color: '#fff', fontSize: 15, fontWeight: '700'},
  ttlSub: {color: 'rgba(255,255,255,0.7)', fontSize: 12, marginTop: 2},

  mid: {position: 'absolute', top: 0, bottom: 0, left: 0, right: 0,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 32},
  cbtn: {width: 58, height: 58, borderRadius: 29, alignItems: 'center',
    justifyContent: 'center'},
  cglyph: {color: '#fff', fontSize: 34, lineHeight: 38},
  cnum: {position: 'absolute', color: '#fff', fontSize: 10, fontWeight: '900',
    top: 26},
  play: {color: '#fff', fontSize: 30, lineHeight: 34},

  bottombar: {position: 'absolute', left: 0, right: 0, bottom: 0,
    paddingHorizontal: 20, paddingTop: 30, paddingBottom: 18,
    backgroundColor: 'rgba(0,0,0,0.45)'},
  progwrap: {paddingVertical: 10, marginBottom: 6},
  track: {height: 3, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.25)',
    justifyContent: 'center'},
  fill: {position: 'absolute', left: 0, top: 0, height: 3, borderRadius: 3,
    backgroundColor: ACCENT},
  dot: {position: 'absolute', width: 13, height: 13, borderRadius: 7,
    backgroundColor: ACCENT, top: -5},
  brow: {flexDirection: 'row', alignItems: 'center',
    justifyContent: 'space-between'},
  time: {color: 'rgba(255,255,255,0.75)', fontSize: 12},
  nextBtn: {backgroundColor: ACCENT, paddingHorizontal: 14, paddingVertical: 7,
    borderRadius: 8},
  nextTxt: {color: '#fff', fontSize: 12, fontWeight: '700'},

  diag: {position: 'absolute', top: 0, left: 0, right: 0,
    backgroundColor: 'rgba(0,0,0,0.75)', paddingHorizontal: 8, paddingVertical: 6},
  diagTxt: {color: '#9ad', fontSize: 11, textAlign: 'left'},
});
