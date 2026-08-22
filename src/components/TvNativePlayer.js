import React, {useRef, useState} from 'react';
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
}) {
  const ref = useRef(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  return (
    <View style={styles.wrap}>
      <Video
        ref={ref}
        source={{uri: src}}
        style={StyleSheet.absoluteFill}
        controls
        paused={false}
        resizeMode="contain"
        // עדכון התקדמות כל 3 שניות — מספיק לשמירת "המשך צפייה" בלי עומס.
        progressUpdateInterval={3000}
        onLoad={() => {
          setReady(true);
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
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {flex: 1, backgroundColor: '#000'},
  center: {position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, justifyContent: 'center', alignItems: 'center'},
  err: {color: '#ddd', fontSize: 16},
});
