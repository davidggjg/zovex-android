import React, {useCallback, useEffect, useRef, useState} from 'react';
import {
  View, Text, StyleSheet, ActivityIndicator, TouchableOpacity, Image, Pressable,
} from 'react-native';
import VlcVideo from './VlcVideo';
import {FS_ENTER, FS_EXIT} from './playerIcons';
import {ltrRow} from '../i18n';
import {markVlcPending, markVlcOk} from '../api/liveEngine';

// נגן שידור חי על libVLC — טלפון בלבד (בטלוויזיה לא נוגעים).
//
// פקדים מינימליים כי אין מה לחפש בשידור חי: ✕, שם הערוץ, LIVE, עצור/נגן,
// ומסך מלא. הכיוון נעול שמאל-לימין כמו ב-NativePlayer (ltrRow).
//
// כשל = onFail, וההורה מחליף ל-ExoPlayer. שלושה מקרים: libVLC מדווח שגיאה,
// הוא לא התחיל לנגן תוך STALL_MS, או שהקריסה הייתה נייטיבית (אז שומר-
// הקריסה ב-api/liveEngine חוסם את VLC בפתיחה הבאה).
const ACCENT = '#e91e8c';
const HIDE_AFTER = 3500;
const STALL_MS = 20000;

export default function LiveVlcPlayer({
  src, title, onClose, onFail, onPlayingChange, onFullscreen,
}) {
  const [playing, setPlaying] = useState(false);   // התחיל לנגן
  const [paused, setPaused] = useState(false);
  const [shown, setShown] = useState(true);
  const [fs, setFs] = useState(false);
  const hideTimer = useRef(null);
  const started = useRef(false);
  const failed = useRef(false);

  const poke = useCallback(() => {
    setShown(true);
    if (hideTimer.current) clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setShown(false), HIDE_AFTER);
  }, []);

  // ב-ref ולא כתלות: ההורה מעביר פונקציה חדשה בכל רינדור, ואם היא הייתה
  // תלות ה-effect היה מתאפס (וטיימר ה-STALL מתחיל מחדש) בכל רינדור שלו.
  const onFailRef = useRef(onFail);
  onFailRef.current = onFail;
  const fail = useCallback(() => {
    if (failed.current) return;
    failed.current = true;
    onFailRef.current && onFailRef.current();
  }, []);

  // סימון לשומר-הקריסה: pending בעלייה, ok ברגע שמנגן או ביציאה רגילה.
  useEffect(() => {
    markVlcPending();
    poke();
    const stall = setTimeout(() => { if (!started.current) fail(); }, STALL_MS);
    return () => {
      clearTimeout(stall);
      if (hideTimer.current) clearTimeout(hideTimer.current);
      markVlcOk();
    };
  }, [poke, fail]);

  useEffect(() => { onPlayingChange && onPlayingChange(playing && !paused); },
    [playing, paused, onPlayingChange]);

  const toggleFs = () => {
    const next = !fs;
    setFs(next);
    poke();
    onFullscreen && onFullscreen(next);
  };

  return (
    <View style={styles.wrap}>
      <VlcVideo
        source={{uri: src}}
        style={StyleSheet.absoluteFill}
        paused={paused}
        resizeMode="contain"
        onPlaying={() => {
          if (!started.current) { started.current = true; markVlcOk(); }
          setPlaying(true);
        }}
        onError={() => fail()}
      />

      <Pressable style={StyleSheet.absoluteFill}
        onPress={() => (shown ? setShown(false) : poke())} />

      {!playing && (
        <ActivityIndicator style={styles.center} color={ACCENT} size="large"
          pointerEvents="none" />
      )}

      {shown && (
        <>
          <View style={[styles.topbar, ltrRow()]} pointerEvents="box-none">
            <TouchableOpacity style={styles.xbtn} onPress={onClose} hitSlop={12}>
              <Text style={styles.xtxt}>✕</Text>
            </TouchableOpacity>
            <View style={styles.ttl} pointerEvents="none">
              <Text style={styles.ttlMain} numberOfLines={1}>{title || ''}</Text>
            </View>
            <View style={styles.xbtn} />
          </View>

          <View style={styles.mid} pointerEvents="box-none">
            <TouchableOpacity style={styles.cbtn}
              onPress={() => { setPaused(p => !p); poke(); }}>
              <Text style={styles.play}>{paused ? '▶' : '❚❚'}</Text>
            </TouchableOpacity>
          </View>

          <View style={[styles.bottombar, ltrRow()]} pointerEvents="box-none">
            <Text style={styles.live}>● LIVE</Text>
            {!!onFullscreen && (
              <TouchableOpacity style={styles.fsBtn} onPress={toggleFs} hitSlop={8}>
                <Image source={fs ? FS_EXIT : FS_ENTER} style={styles.fsIcon}
                  resizeMode="contain" />
              </TouchableOpacity>
            )}
          </View>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {flex: 1, backgroundColor: '#000'},
  center: {position: 'absolute', top: 0, bottom: 0, left: 0, right: 0,
    justifyContent: 'center', alignItems: 'center'},
  topbar: {position: 'absolute', top: 0, left: 0, right: 0, paddingHorizontal: 16,
    paddingTop: 14, paddingBottom: 34, alignItems: 'flex-start',
    backgroundColor: 'rgba(0,0,0,0.55)'},
  xbtn: {width: 34, alignItems: 'center', justifyContent: 'center'},
  xtxt: {color: '#fff', fontSize: 24, lineHeight: 26},
  ttl: {flex: 1, alignItems: 'center', paddingTop: 2},
  ttlMain: {color: '#fff', fontSize: 15, fontWeight: '700'},
  mid: {position: 'absolute', top: 0, bottom: 0, left: 0, right: 0,
    alignItems: 'center', justifyContent: 'center'},
  cbtn: {width: 62, height: 62, borderRadius: 31, alignItems: 'center',
    justifyContent: 'center'},
  play: {color: '#fff', fontSize: 30, lineHeight: 34},
  bottombar: {position: 'absolute', left: 0, right: 0, bottom: 0,
    paddingHorizontal: 20, paddingTop: 20, paddingBottom: 18,
    alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: 'rgba(0,0,0,0.45)'},
  live: {color: '#ff4d5e', fontSize: 13, fontWeight: '800'},
  fsBtn: {width: 40, height: 40, alignItems: 'center', justifyContent: 'center'},
  fsIcon: {width: 21, height: 21},
});
