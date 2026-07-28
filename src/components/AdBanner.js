import React from 'react';
import {View, StyleSheet} from 'react-native';
import {WebView} from 'react-native-webview';

const AD_KEY = '833479e14706e97fe2b8acbc143a4963';

// אותה מודעת Adsterra שבאתר (davidggjg.github.io/zovex), בתוך WebView -
// זו הדרך התקנית להריץ סקריפט מבוסס document.write כמו הזה בתוך אפליקציה
// native, בלי לגעת ב-DOM/View tree של שאר האפליקציה.
const AD_HTML = `<!DOCTYPE html>
<html>
<head><style>body{margin:0;padding:0;overflow:hidden;background:transparent;}</style></head>
<body>
  <script>
    atOptions = {
      'key' : '${AD_KEY}',
      'format' : 'iframe',
      'height' : 50,
      'width' : 320,
      'params' : {}
    };
  </script>
  <script src="https://www.highperformanceformat.com/${AD_KEY}/invoke.js"></script>
</body>
</html>`;

export default function AdBanner() {
  return (
    <View style={styles.wrap} pointerEvents="box-none">
      <WebView
        source={{html: AD_HTML}}
        style={styles.webview}
        originWhitelist={['*']}
        javaScriptEnabled
        scrollEnabled={false}
        backgroundColor="transparent"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    alignItems: 'center',
    zIndex: 200,
    elevation: 200,
  },
  webview: {
    width: 320,
    height: 50,
    backgroundColor: 'transparent',
  },
});
