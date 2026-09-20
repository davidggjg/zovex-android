import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ltrRow, pinLeft, pinRight, t} from '../i18n';
import {
  View, Text, StyleSheet, ActivityIndicator, TouchableOpacity, Image,
  PanResponder, Pressable,
} from 'react-native';
// ExoPlayer. ניסיון המעבר ל-libVLC בוטל: הוא הקריס בלחיצה על פליי, וגם
// אחרי שאותר ותוקן בו באג אמיתי (ראה scripts/fix-vlc-autoplay-crash.sh)
// הוא קרס שוב. בלי adb אין דרך לנפות קריסה נייטיבית בלי לנחש, וכל ניחוש
// עולה למשתמש אפליקציה שבורה. המתאם VlcVideo.js נשאר בעץ ומקמפל, כך
// שחזרה לניסיון היא שורה אחת — אבל רק כשיהיה לוג.
//
// את בעיית התוכן שבגללה רצינו את VLC פותרים כאן במסלול שכבר מוכח באתר:
// נפילה ל-/vt, שממיר בשרת עם ffmpeg. ראה vtFallbackSrc למטה.
import Video from 'react-native-video';
import {BACK10, FS_ENTER, FS_EXIT, FWD10} from './playerIcons';

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

// נפילה להמרה בשרת, זהה למה שהאתר עושה ומוכח שם.
//
// ExoPlayer לא פותח AVI (ומכולות/קודקים נוספים), והשרת כבר יודע להמיר
// אותם ל-HLS דרך /vt — אותה חתימה של /stream, ולכן ה-exp+sig שבקישור
// עוברים כמו שהם. ExoPlayer מנגן HLS מצוין, אז זה עובד בלי שום תלות
// נייטיבית חדשה ובלי לוותר על אנדרואיד 7.
export function vtFallbackSrc(src) {
  if (!src) return null;
  const m = String(src).match(/^(.*)\/stream\/(-?\d+)\/(\d+)(\?.*)?$/);
  if (!m) return null;                       // לא קישור /stream שלנו
  return `${m[1]}/vt/${m[2]}/${m[3]}/index.m3u8${m[4] || ''}`;
}

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
  onNoAudio,
  onNext,
  onPlayingChange,
  onFullscreen,
  debug = false,
}) {
  const ref = useRef(null);
  // כשהניגון הישיר נכשל, עוברים פעם אחת למסלול ההמרה בשרת.
  const [vtSrc, setVtSrc] = useState(null);
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

  // מהירות הפעלה. rate היא הבחירה של הצופה; held היא הזמנית של הלחיצה
  // הארוכה, ולכן שחרור האצבע חוזר בדיוק לבחירה ולא ל-1.
  const RATES = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
  const [rate, setRate] = useState(1);
  const [held, setHeld] = useState(false);
  const [rateSheet, setRateSheet] = useState(false);
  const effRate = held ? 2 : rate;

  // מסך מלא. היה קיים רק בנגן ה-WebView (#fsbtn), ומשעבר הנייטיב להיות
  // הנגן הראשי הכפתור נעלם למשתמש. אותו מסלול בדיוק: StatusBar + כיוון
  // מסך, דרך PipModule שב-PlayerScreen. בטלוויזיה אין כפתור — המסך שם
  // מלא ולרוחב ממילא, וכפיית כיוון משנה את גודל החלון ומקלקלת פריסה.
  const [fs, setFs] = useState(false);
  const toggleFs = () => {
    const next = !fs;
    setFs(next);
    poke();
    onFullscreen && onFullscreen(next);
  };

  const frac = dur > 0 ? Math.max(0, Math.min(1, pos / dur)) : 0;

  return (
    <View style={styles.wrap}>
      <Video
        ref={ref}
        source={{uri: vtSrc || src, minLoadRetryCount: 6}}
        style={StyleSheet.absoluteFill}
        controls={false}
        paused={paused}
        rate={effRate}
        resizeMode="contain"
        progressUpdateInterval={500}
        onLoad={d => {
          setReady(true);
          const dd = d?.duration || 0;
          durRef.current = dd;
          setDur(dd);
          // ── רצועת קול שקיימת בקובץ ואף אחד לא בחר בה ──────────────────
          //
          // אומת בקוד של react-native-video 6.4.5:
          // getAudioTrackInfo מחזיר **כל** קבוצת רצועה שיש בקובץ, בלי
          // לסנן לפי תמיכה (בשונה מ-getVideoTrackInfo, שמסנן ב-
          // isFormatSupported), ואת selected הוא לוקח מ-
          // player.getCurrentTrackSelections(). ExoPlayer לא בוחר רצועה
          // שאין לה מפענח — ולכן "יש רצועות, אף אחת לא נבחרה" פירושו
          // בדיוק: הקובץ מכיל קול, והמכשיר הזה לא יודע לפענח אותו.
          //
          // זה הכשל השקט: ExoPlayer לא זורק onError על זה. הווידאו מנגן
          // שעתיים בלי קול, ושום מדרגה בסולם הנפילה-אחורה לא נדרכת, כי
          // כולן תלויות בשגיאה. מכאן יורדים ל-/vh, שממיר את הקול בשרת.
          const at = d?.audioTracks || [];
          if (at.length && !at.some(t => t.selected) && onNoAudio && !vtSrc) {
            onNoAudio(d?.currentTime || startTime || 0,
                      at.map(t => t.type || '?').join(','));
          }
          if (debug) {
            const a = (d?.audioTracks || []).map(
              t => `${t.index}:${t.type || '?'}${t.selected ? '*' : ''}`).join(' ');
            const v = (d?.videoTracks || []).map(
              t => `${t.index}:${t.codecs || '?'}${t.selected ? '*' : ''}`).join(' ');
            // איזה מסלול מנגן עכשיו. בלי זה אי אפשר לדעת אם המעבר להמרה
            // בשרת בכלל קרה, או שאנחנו עדיין על הקובץ המקורי.
            const cur = vtSrc || src || '';
            const route = cur.includes('/vt/') ? 'vt'
                        : cur.includes('/vh/') ? 'vh'
                        : cur.includes('/fs/') ? 'fs' : 'stream';
            setDiag(`[${route}] אודיו[${a || 'אין'}] וידאו[${v || 'אין'}] ${Math.round(dd)}ש`);
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
          // ניסיון אחד למסלול ההמרה לפני שמדווחים כשלון. מנסים על כל
          // שגיאה ולא לפי קוד מסוים: מיפוי קודי ExoPlayer שביר, והמחיר
          // של ניסיון מיותר הוא שנייה אחת, בזמן שהמחיר של פספוס הוא
          // סרט שלא נפתח בכלל.
          if (!vtSrc) {
            const alt = vtFallbackSrc(src);
            if (alt) {
              if (debug) setDiag(d => `${d}\nנפילה ל-/vt`);
              setVtSrc(alt);
              return;
            }
          }
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
        onPress={() => {
          if (rateSheet) { setRateSheet(false); return; }
          shown ? setShown(false) : poke();
        }}
        onLongPress={() => setHeld(true)}
        delayLongPress={450}
        onPressOut={() => setHeld(false)} />
      {held && (
        <View style={styles.holdBadge} pointerEvents="none">
          <Text style={styles.holdTxt}>×2 ⏩</Text>
        </View>
      )}

      {!ready && <ActivityIndicator style={styles.center} color={ACCENT} size="large" />}

      {shown && (
        <>
          <View
          // הסרגל נקרא שמאל-לימין בשתי השפות, ולא לפי כיוון הכתיבה. ה-✕
          // נעול משמאל וסמל השידור לטלוויזיה בימין (CastLayer) — הצדדים
          // הנגדיים, תמיד. קודם הכיוון נגזר מהשפה, ואז החלפת שפה הפילה את
          // שניהם לאותה פינה. אין כאן טקסט שצריך יישור: הכותרת ממורכזת.
          style={[styles.topbar, ltrRow()]}
          pointerEvents="box-none">
            <TouchableOpacity style={styles.xbtn} onPress={onClose} hitSlop={12}>
              <Text style={styles.xtxt}>✕</Text>
            </TouchableOpacity>
            <View style={styles.ttl} pointerEvents="none">
              <Text style={styles.ttlMain} numberOfLines={1}>{title || ''}</Text>
              {!!subtitle && <Text style={styles.ttlSub} numberOfLines={1}>{subtitle}</Text>}
            </View>
            <View style={styles.xbtn} />
          </View>

          {/* אחורה תמיד משמאל וקדימה תמיד מימין. תחת היפוך הפריסה השניים
              התחלפו ביניהם, וזה היה מבלבל יותר מכל: הכפתור השמאלי קידם. */}
          <View style={[styles.mid, ltrRow()]} pointerEvents="box-none">
            <TouchableOpacity style={styles.cbtn} onPress={() => skip(-10)} hitSlop={8}>
              <Image source={BACK10} style={styles.skipIcon} resizeMode="contain" />
            </TouchableOpacity>
            <TouchableOpacity style={styles.cbtn}
              onPress={() => { setPaused(p => !p); poke(); }}>
              <Text style={styles.play}>{paused ? '▶' : '❚❚'}</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.cbtn} onPress={() => skip(10)} hitSlop={8}>
              <Image source={FWD10} style={styles.skipIcon} resizeMode="contain" />
            </TouchableOpacity>
          </View>

          <View style={styles.bottombar} pointerEvents="box-none">
            <View style={styles.progwrap} {...pan.panHandlers}
              onLayout={e => { barWRef.current = e.nativeEvent.layout.width || 1;
                               setBarW(barWRef.current); }}>
              {/* pinLeft: הפס והנקודה נמדדים מהקצה השמאלי הפיזי. תחת היפוך
                  הפריסה left הפך ל-right, והפס התמלא מהצד ההפוך לכיוון
                  שבו הסרט מתקדם. */}
              <View style={styles.track}>
                <View style={[styles.fill, pinLeft(0), {width: `${frac * 100}%`}]} />
                <View style={[styles.dot, pinLeft(Math.max(0, frac * barW - 6.5))]} />
              </View>
            </View>
            <View style={[styles.brow, ltrRow()]}>
              <Text style={styles.time}>{fmt(pos)} / {fmt(dur)}</Text>
              <View style={[styles.bright, ltrRow()]}>
                {hasNext && (
                  <TouchableOpacity style={styles.nextBtn} onPress={onNext}>
                    <Text style={styles.nextTxt}>
                      {nextLabel ? `${t('player.nextLabel')}: ${nextLabel}` : t('player.nextEpisode')}
                    </Text>
                  </TouchableOpacity>
                )}
                <TouchableOpacity style={[styles.gearBtn, ltrRow()]} hitSlop={8}
                  onPress={() => { setRateSheet(v => !v); poke(); }}>
                  <Text style={styles.gearTxt}>⚙</Text>
                  {rate !== 1 && <Text style={styles.gearRate}>{rate}x</Text>}
                </TouchableOpacity>
                {!!onFullscreen && (
                  <TouchableOpacity style={styles.fsBtn} onPress={toggleFs} hitSlop={8}>
                    <Image source={fs ? FS_EXIT : FS_ENTER} style={styles.fsIcon}
                      resizeMode="contain" />
                  </TouchableOpacity>
                )}
              </View>
            </View>
          </View>

          {rateSheet && (
            <View style={[styles.sheet, pinRight(16)]}>
              <Text style={styles.sheetHead}>{t('player.speed')}</Text>
              {RATES.map(r => (
                <TouchableOpacity key={r}
                  style={[styles.sheetOpt, ltrRow(), r === rate && styles.sheetOptSel]}
                  onPress={() => { setRate(r); setRateSheet(false); poke(); }}>
                  <Text style={[styles.sheetTxt, r === rate && styles.sheetTxtSel]}>
                    {r === 1 ? t('player.speedNormal') : `${r}x`}
                  </Text>
                  <Text style={styles.sheetTxtSel}>{r === rate ? '✓' : ''}</Text>
                </TouchableOpacity>
              ))}
            </View>
          )}
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
  // הכיוון נקבע ב-render דרך ltrRow, אחרת "1.5x" והגלגל התחלפו ביניהם.
  gearBtn: {paddingHorizontal: 10, paddingVertical: 4, alignItems: 'center',
            justifyContent: 'center'},
  gearTxt: {color: '#fff', fontSize: 18},
  gearRate: {color: '#8db4ff', fontSize: 11, fontWeight: '700', marginLeft: 3},
  // הצד נקבע ב-render דרך pinRight — ראה ההערה שם.
  sheet: {position: 'absolute', bottom: 92, zIndex: 60, minWidth: 170,
          backgroundColor: 'rgba(22,24,30,0.97)', borderRadius: 14, paddingVertical: 10,
          paddingHorizontal: 8},
  sheetHead: {color: '#9aa0a6', fontSize: 12, paddingHorizontal: 10, paddingBottom: 6,
              textAlign: 'center'},
  // הכיוון נקבע ב-render דרך ltrRow: התווית משמאל וה-✓ מימין, בשתי השפות.
  sheetOpt: {alignItems: 'center', justifyContent: 'space-between',
             paddingVertical: 10, paddingHorizontal: 12, borderRadius: 9},
  sheetOptSel: {backgroundColor: 'rgba(47,109,246,0.22)'},
  sheetTxt: {color: '#e8eaed', fontSize: 15},
  sheetTxtSel: {color: '#8db4ff', fontWeight: '700'},
  // תג שמופיע כל עוד מחזיקים — משוב שהמהירות אכן השתנתה.
  holdBadge: {position: 'absolute', top: 22, alignSelf: 'center', zIndex: 60,
              backgroundColor: 'rgba(0,0,0,0.72)', paddingVertical: 7,
              paddingHorizontal: 16, borderRadius: 20},
  holdTxt: {color: '#fff', fontSize: 15, fontWeight: '700'},
  wrap: {flex: 1, backgroundColor: '#000'},
  center: {position: 'absolute', top: 0, bottom: 0, left: 0, right: 0,
    justifyContent: 'center', alignItems: 'center'},

  topbar: {
    position: 'absolute', top: 0, left: 0, right: 0, paddingHorizontal: 16,
    paddingTop: 14, paddingBottom: 34,
    // הכיוון נקבע בזמן הציור דרך ltrRow ולא כאן.
    alignItems: 'flex-start', backgroundColor: 'rgba(0,0,0,0.55)'},
  xbtn: {width: 34, alignItems: 'center', justifyContent: 'center'},
  xtxt: {color: '#fff', fontSize: 24, lineHeight: 26},
  ttl: {flex: 1, alignItems: 'center', paddingTop: 2},
  ttlMain: {color: '#fff', fontSize: 15, fontWeight: '700'},
  ttlSub: {color: 'rgba(255,255,255,0.7)', fontSize: 12, marginTop: 2},

  // הכיוון נקבע ב-render דרך ltrRow.
  mid: {position: 'absolute', top: 0, bottom: 0, left: 0, right: 0,
    alignItems: 'center', justifyContent: 'center', gap: 34},
  cbtn: {width: 58, height: 58, borderRadius: 29, alignItems: 'center',
    justifyContent: 'center'},
  skipIcon: {width: 42, height: 42},
  play: {color: '#fff', fontSize: 30, lineHeight: 34},

  bottombar: {position: 'absolute', left: 0, right: 0, bottom: 0,
    paddingHorizontal: 20, paddingTop: 30, paddingBottom: 18,
    backgroundColor: 'rgba(0,0,0,0.45)'},
  progwrap: {paddingVertical: 10, marginBottom: 6},
  track: {height: 3, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.25)',
    justifyContent: 'center'},
  // left נקבע ב-render דרך pinLeft — ראה ההערה שם.
  fill: {position: 'absolute', top: 0, height: 3, borderRadius: 3,
    backgroundColor: ACCENT},
  dot: {position: 'absolute', width: 13, height: 13, borderRadius: 7,
    backgroundColor: ACCENT, top: -5},
  brow: {alignItems: 'center', justifyContent: 'space-between'},
  bright: {alignItems: 'center', gap: 6},
  fsBtn: {width: 40, height: 40, alignItems: 'center', justifyContent: 'center'},
  fsIcon: {width: 21, height: 21},
  time: {color: 'rgba(255,255,255,0.75)', fontSize: 12},
  nextBtn: {backgroundColor: ACCENT, paddingHorizontal: 14, paddingVertical: 7,
    borderRadius: 8},
  nextTxt: {color: '#fff', fontSize: 12, fontWeight: '700'},

  diag: {position: 'absolute', top: 0, left: 0, right: 0,
    backgroundColor: 'rgba(0,0,0,0.75)', paddingHorizontal: 8, paddingVertical: 6},
  diagTxt: {color: '#9ad', fontSize: 11, textAlign: 'left'},
});
