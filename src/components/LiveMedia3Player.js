import React, {useCallback, useEffect, useRef, useState} from 'react';
import Video from 'react-native-video';
import {
  View, Text, StyleSheet, ActivityIndicator, TouchableOpacity, Image, Pressable,
} from 'react-native';
import {FS_ENTER, FS_EXIT} from './playerIcons';
import {ltrRow} from '../i18n';

// Temporary compatibility name: this component now uses the same Media3 / ExoPlayer
// engine as NativePlayer and TvNativePlayer. No libVLC is loaded.
const ACCENT = '#e91e8c';
const HIDE_AFTER = 3500;
const STALL_MS = 25000;

function liveSource(src) {
  const uri = String(src || '');
  // IPTV relay URLs often have no file extension. Prefer HLS for such live URLs,
  // but preserve obvious direct-stream/container types when the URL tells us.
  if (/\.mpd(?:$|[?#])/i.test(uri)) return {uri, type: 'mpd'};
  if (/\.ism(?:$|[?#])/i.test(uri)) return {uri, type: 'ism'};
  if (/\.(?:ts|mpeg|mpg)(?:$|[?#])/i.test(uri)) return {uri};
  if (/\.(?:mp4|m4v|mov)(?:$|[?#])/i.test(uri)) return {uri, type: 'mp4'};
  return {uri, type: 'm3u8'};
}

export default function LiveMedia3Player({
  src, title, onClose, onFail, onPlayingChange, onFullscreen,
}) {
  const player = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [paused, setPaused] = useState(false);
  const [buffering, setBuffering] = useState(true);
  const [shown, setShown] = useState(true);
  const [fs, setFs] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const hideTimer = useRef(null);
  const started = useRef(false);
  const onFailRef = useRef(onFail);
  onFailRef.current = onFail;

  const poke = useCallback(() => {
    setShown(true);
    if (hideTimer.current) clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setShown(false), HIDE_AFTER);
  }, []);

  useEffect(() => {
    started.current = false;
    setError('');
    setPlaying(false);
    setBuffering(true);
    poke();
    const stall = setTimeout(() => {
      if (!started.current) {
        setBuffering(false);
        setError('השידור לא התחיל בזמן. בדוק את החיבור ונסה שוב.');
        onFailRef.current && onFailRef.current('stall25s');
      }
    }, STALL_MS);
    return () => {
      clearTimeout(stall);
      if (hideTimer.current) clearTimeout(hideTimer.current);
    };
  }, [src, attempt, poke]);

  useEffect(() => {
    onPlayingChange && onPlayingChange(playing && !paused && !error);
  }, [playing, paused, error, onPlayingChange]);

  const toggleFs = () => {
    const next = !fs;
    setFs(next);
    poke();
    onFullscreen && onFullscreen(next);
  };

  const fail = e => {
    setBuffering(false);
    setPlaying(false);
    const msg = e?.error?.errorString || e?.error?.localizedDescription || e?.error?.errorCode;
    setError(msg ? `לא ניתן לנגן את השידור (${msg}).` : 'לא ניתן לנגן את השידור.');
    onFailRef.current && onFailRef.current('media3-error');
  };

  return (
    <View style={styles.wrap}>
      {!error && <Video
        key={`${src}:${attempt}`}
        ref={player}
        source={liveSource(src)}
        style={StyleSheet.absoluteFill}
        paused={paused}
        controls={false}
        resizeMode="contain"
        repeat={false}
        playInBackground={false}
        playWhenInactive={false}
        progressUpdateInterval={1000}
        bufferConfig={{
          minBufferMs: 8000,
          maxBufferMs: 30000,
          bufferForPlaybackMs: 1000,
          bufferForPlaybackAfterRebufferMs: 2500,
        }}
        onLoadStart={() => { setBuffering(true); setError(''); }}
        onLoad={() => setBuffering(false)}
        onBuffer={({isBuffering}) => setBuffering(!!isBuffering)}
        onReadyForDisplay={() => {
          started.current = true;
          setBuffering(false);
          setPlaying(true);
        }}
        onPlaybackStateChanged={({isPlaying}) => setPlaying(!!isPlaying)}
        onError={fail}
      />}

      <Pressable style={StyleSheet.absoluteFill} onPress={() => (shown ? setShown(false) : poke())} />

      {(buffering || (!playing && !error)) && !error && (
        <ActivityIndicator style={styles.center} color={ACCENT} size="large" pointerEvents="none" />
      )}

      {!!error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity style={styles.retryBtn} onPress={() => setAttempt(v => v + 1)}>
            <Text style={styles.retryText}>נסה שוב</Text>
          </TouchableOpacity>
          {!!onClose && <TouchableOpacity onPress={onClose} style={styles.retryBtn}>
            <Text style={styles.retryText}>חזרה</Text>
          </TouchableOpacity>}
        </View>
      )}

      {shown && !error && <>
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
          <TouchableOpacity style={styles.cbtn} onPress={() => { setPaused(p => !p); poke(); }}>
            <Text style={styles.play}>{paused ? '▶' : '❚❚'}</Text>
          </TouchableOpacity>
        </View>
        <View style={[styles.bottombar, ltrRow()]} pointerEvents="box-none">
          <Text style={styles.live}>● LIVE</Text>
          {!!onFullscreen && <TouchableOpacity style={styles.fsBtn} onPress={toggleFs} hitSlop={8}>
            <Image source={fs ? FS_EXIT : FS_ENTER} style={styles.fsIcon} resizeMode="contain" />
          </TouchableOpacity>}
        </View>
      </>}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {flex: 1, backgroundColor: '#000'},
  center: {position: 'absolute', top: 0, bottom: 0, left: 0, right: 0,
    justifyContent: 'center', alignItems: 'center'},
  topbar: {position: 'absolute', top: 0, left: 0, right: 0, paddingHorizontal: 16,
    paddingTop: 14, paddingBottom: 34, alignItems: 'flex-start', backgroundColor: 'rgba(0,0,0,0.55)'},
  xbtn: {width: 34, alignItems: 'center', justifyContent: 'center'},
  xtxt: {color: '#fff', fontSize: 24, lineHeight: 26},
  ttl: {flex: 1, alignItems: 'center', paddingTop: 2},
  ttlMain: {color: '#fff', fontSize: 15, fontWeight: '700'},
  mid: {position: 'absolute', top: 0, bottom: 0, left: 0, right: 0,
    alignItems: 'center', justifyContent: 'center'},
  cbtn: {width: 62, height: 62, borderRadius: 31, alignItems: 'center', justifyContent: 'center'},
  play: {color: '#fff', fontSize: 30, lineHeight: 34},
  bottombar: {position: 'absolute', left: 0, right: 0, bottom: 0, paddingHorizontal: 20,
    paddingTop: 20, paddingBottom: 18, alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: 'rgba(0,0,0,0.45)'},
  live: {color: '#ff4d5e', fontSize: 13, fontWeight: '800'},
  fsBtn: {width: 40, height: 40, alignItems: 'center', justifyContent: 'center'},
  fsIcon: {width: 21, height: 21},
  errorBox: {position: 'absolute', left: 24, right: 24, top: '30%', alignItems: 'center', gap: 12},
  errorText: {color: '#fff', textAlign: 'center', fontSize: 16},
  retryBtn: {paddingHorizontal: 20, paddingVertical: 10, borderRadius: 8, backgroundColor: '#e91e8c'},
  retryText: {color: '#fff', fontWeight: '700'},
});
