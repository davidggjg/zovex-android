import React, {useMemo, useEffect, useRef} from 'react';
import {View, StyleSheet, Text} from 'react-native';
import {WebView} from 'react-native-webview';
import {saveProgress, saveHistory} from '../api/movies';
import {getUserId} from '../api/userStore';

function buildEmbedUrl(movie) {
  const {type, video_id, video_url} = movie;
  if (type === 'youtube') {
    return `https://www.youtube.com/embed/${video_id}?autoplay=1&playsinline=1`;
  }
  if (type === 'kaltura') {
    const parts = (video_id || '').split('/');
    if (parts.length === 3) {
      return `https://cdnapisec.kaltura.com/p/${parts[0]}/embedPlaykitJs/uiconf_id/${parts[1]}?iframeembed=true&entry_id=${parts[2]}&autoPlay=true`;
    }
    return video_url || '';
  }
  if (type === 'dailymotion') {
    return `https://www.dailymotion.com/embed/video/${video_id}?autoplay=1`;
  }
  if (type === 'drive') {
    return `https://drive.google.com/file/d/${video_id}/preview`;
  }
  if (type === 'direct') return video_url || video_id || null;
  return video_url || '';
}

function buildDirectHtml(url, startTime = 0) {
  return `<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { margin:0; padding:0; box-sizing:border-box; background:#000; }
  video { width:100vw; height:100vh; object-fit:contain; }
</style>
</head>
<body>
<video id="v" controls autoplay playsinline>
  <source src="${url}">
</video>
<script>
  var v = document.getElementById('v');
  var startAt = ${startTime};
  v.addEventListener('loadedmetadata', function() {
    if (startAt > 0) v.currentTime = startAt;
    v.play().catch(function(){});
    setInterval(function(){
      if (!v.paused && v.duration) {
        window.ReactNativeWebView && window.ReactNativeWebView.postMessage(
          JSON.stringify({type:'progress', position: Math.floor(v.currentTime), duration: Math.floor(v.duration)})
        );
      }
    }, 10000);
  });
</script>
</body>
</html>`;
}

function buildHlsHtml(url, startTime = 0) {
  return `<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { margin:0; padding:0; box-sizing:border-box; background:#000; }
  video { width:100vw; height:100vh; object-fit:contain; }
</style>
</head>
<body>
<video id="v" controls autoplay playsinline></video>
<script src="https://cdnjs.cloudflare.com/ajax/libs/hls.js/1.4.12/hls.min.js"></script>
<script>
  var v = document.getElementById('v');
  var src = "${url}";
  var startAt = ${startTime};
  function onReady() {
    if (startAt > 0) v.currentTime = startAt;
    v.play();
    setInterval(function(){
      if (!v.paused && v.duration) {
        window.ReactNativeWebView && window.ReactNativeWebView.postMessage(
          JSON.stringify({type:'progress', position: Math.floor(v.currentTime), duration: Math.floor(v.duration)})
        );
      }
    }, 10000);
  }
  if (Hls.isSupported()) {
    var hls = new Hls();
    hls.loadSource(src);
    hls.attachMedia(v);
    hls.on(Hls.Events.MANIFEST_PARSED, onReady);
  } else if (v.canPlayType('application/vnd.apple.mpegurl')) {
    v.src = src;
    v.addEventListener('loadedmetadata', onReady);
  }
</script>
</body>
</html>`;
}

export default function PlayerScreen({route}) {
  const {movie, startTime = 0} = route.params;
  const embedUrl = useMemo(() => buildEmbedUrl(movie), [movie]);
  const userId = getUserId();
  const progressRef = useRef({position: startTime, duration: 0});

  const directSrc = movie.video_url || movie.video_id || '';
  const isDirectHls =
    movie.type === 'direct' &&
    (directSrc.includes('.m3u8'));
  const isDirectVideo = movie.type === 'direct' && !isDirectHls;

  // Save history entry when player opens
  useEffect(() => {
    saveHistory(movie.id, movie.title, movie.thumbnail_url, userId);
    return () => {
      // Save final progress on unmount
      const {position, duration} = progressRef.current;
      if (position > 5 && duration > 0) {
        saveProgress(movie.id, position, duration, userId);
      }
    };
  }, [movie.id, movie.title, movie.thumbnail_url, userId]);

  const onMessage = event => {
    try {
      const m = JSON.parse(event.nativeEvent.data);
      if (m.type === 'progress') {
        progressRef.current = {position: m.position, duration: m.duration};
        // Auto-save progress every 10s (from the interval in the injected JS)
        saveProgress(movie.id, m.position, m.duration, userId);
      }
    } catch (_) {}
  };

  if (isDirectHls) {
    return (
      <View style={styles.container}>
        <WebView
          source={{html: buildHlsHtml(directSrc, startTime)}}
          style={styles.player}
          allowsInlineMediaPlayback
          mediaPlaybackRequiresUserAction={false}
          allowsFullscreenVideo
          javaScriptEnabled
          onMessage={onMessage}
        />
      </View>
    );
  }

  if (isDirectVideo) {
    return (
      <View style={styles.container}>
        <WebView
          source={{html: buildDirectHtml(directSrc, startTime)}}
          style={styles.player}
          allowsInlineMediaPlayback
          mediaPlaybackRequiresUserAction={false}
          allowsFullscreenVideo
          javaScriptEnabled
          onMessage={onMessage}
        />
      </View>
    );
  }

  if (!embedUrl) {
    return (
      <View style={styles.error}>
        <Text style={styles.errorText}>לא ניתן להפעיל סרטון זה</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <WebView
        source={{uri: embedUrl}}
        style={styles.player}
        allowsInlineMediaPlayback
        mediaPlaybackRequiresUserAction={false}
        allowsFullscreenVideo
        javaScriptEnabled
        domStorageEnabled
        startInLoadingState
        onMessage={onMessage}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#000'},
  player: {flex: 1, backgroundColor: '#000'},
  error: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#000',
  },
  errorText: {color: '#aaa', fontSize: 16},
});
