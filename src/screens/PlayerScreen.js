import React, {useMemo} from 'react';
import {View, StyleSheet, Text} from 'react-native';
import {WebView} from 'react-native-webview';

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
  if (type === 'direct') {
    return null;
  }
  return video_url || '';
}

function buildHlsHtml(url) {
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
  if (Hls.isSupported()) {
    var hls = new Hls();
    hls.loadSource(src);
    hls.attachMedia(v);
    hls.on(Hls.Events.MANIFEST_PARSED, function() { v.play(); });
  } else if (v.canPlayType('application/vnd.apple.mpegurl')) {
    v.src = src;
    v.play();
  }
</script>
</body>
</html>`;
}

export default function PlayerScreen({route}) {
  const {movie} = route.params;
  const embedUrl = useMemo(() => buildEmbedUrl(movie), [movie]);

  const isDirectHls =
    movie.type === 'direct' &&
    ((movie.video_id || '').includes('.m3u8') ||
      (movie.video_url || '').includes('.m3u8'));

  if (isDirectHls) {
    return (
      <View style={styles.container}>
        <WebView
          source={{html: buildHlsHtml(movie.video_id || movie.video_url)}}
          style={styles.player}
          allowsInlineMediaPlayback
          mediaPlaybackRequiresUserAction={false}
          allowsFullscreenVideo
          javaScriptEnabled
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
