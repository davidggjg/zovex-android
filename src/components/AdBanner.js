import React from 'react';
import {View, StyleSheet, Linking} from 'react-native';
import {WebView} from 'react-native-webview';

const AD_KEY = '8050516fd44627d57aee36c0f8306419';
const AD_BASE_URL = 'https://zovex.duckdns.org/';

// אותה מודעת Adsterra שבאתר (zovex.duckdns.org). baseUrl גורם
// ל-WebView לשלוח את הדומיין הרשום כמקור הדף (הזוהה נדרש כדי שהמודעה
// תיטען בכלל, ולא תחזור ריקה).
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

// מודעות מובייל נוהגות: (1) לנסות deep-link לאפליקציה (aliexpress:// /
// market:// / intent://) שה-WebView לא יודע לפתוח בעצמו, ו-(2) לנווט את
// כל ה-WebView (top-frame) לאתר יעד שלם במקום להישאר בתוך ה-iframe
// הפנימי של קריאייטיב המודעה. שני המקרים נפתחים ב-OS/דפדפן חיצוני
// במקום להשתלט על הבאנר הקטן; ניווט פנימי (iframe) של המודעה עצמה מותר.
function handleNavigation(request) {
  const {url, isTopFrame} = request;
  if (/^https?:/i.test(url) && (!isTopFrame || url === AD_BASE_URL)) return true;
  Linking.openURL(url).catch(() => {});
  return false;
}

export default function AdBanner() {
  return (
    <View style={styles.wrap} pointerEvents="box-none">
      <WebView
        source={{html: AD_HTML, baseUrl: AD_BASE_URL}}
        style={styles.webview}
        originWhitelist={['*']}
        javaScriptEnabled
        domStorageEnabled
        thirdPartyCookiesEnabled
        mixedContentMode="always"
        scrollEnabled={false}
        backgroundColor="transparent"
        onShouldStartLoadWithRequest={handleNavigation}
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
  },
  webview: {
    width: 320,
    height: 50,
    backgroundColor: 'transparent',
  },
});
