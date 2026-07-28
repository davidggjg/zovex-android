import React, {useState} from 'react';
import {View, Text, StyleSheet, Linking} from 'react-native';
import {WebView} from 'react-native-webview';

// מודעות מובייל נוהגות לנסות לפתוח קישורי deep-link לאפליקציות (סכימות
// כמו aliexpress:// / market:// / intent://) - ה-WebView לא יודע לנווט
// אליהן בעצמו וקורס עם ERR_UNKNOWN_URL_SCHEME. צריך ליירט ולהעביר ל-OS.
function handleNavigation(request) {
  const {url} = request;
  if (/^(https?:|about:blank|data:)/i.test(url)) return true;
  Linking.openURL(url).catch(() => {});
  return false;
}

const AD_KEY = '833479e14706e97fe2b8acbc143a4963';

// גרסת דיבאג: מדווחת על כל שלב דרך window.ReactNativeWebView.postMessage,
// ובנוסף - ה-WebView עטוף בקופסה עם רקע צהוב זמני, כדי לראות אם השטח שלו
// בכלל נתפס על המסך (בלי קשר לשאלה אם המודעה עצמה נטענה).
const AD_HTML = `<!DOCTYPE html>
<html>
<head><style>body{margin:0;padding:0;overflow:hidden;background:transparent;}</style></head>
<body>
  <script>
    function report(msg){ try{ window.ReactNativeWebView.postMessage(msg); }catch(e){} }
    report('1-html-script-started');
    atOptions = {
      'key' : '${AD_KEY}',
      'format' : 'iframe',
      'height' : 50,
      'width' : 320,
      'params' : {}
    };
    report('2-atOptions-set');
  </script>
  <script
    src="https://www.highperformanceformat.com/${AD_KEY}/invoke.js"
    onload="report('3-invoke-onload-fired')"
    onerror="report('3-invoke-ONERROR-fired')"
  ></script>
  <script>report('4-after-invoke-tag');</script>
</body>
</html>`;

export default function AdBanner() {
  const [logs, setLogs] = useState([]);
  const [webviewError, setWebviewError] = useState(null);

  return (
    <View style={styles.wrap} pointerEvents="box-none">
      <Text style={styles.debugText}>
        AD DEBUG: {webviewError ? `WEBVIEW-ERROR: ${webviewError}` : logs.length === 0 ? 'waiting...' : logs.join(' | ')}
      </Text>
      <View style={styles.webviewBox}>
        <WebView
          source={{html: AD_HTML, baseUrl: 'https://davidggjg.github.io/zovex/'}}
          style={styles.webview}
          originWhitelist={['*']}
          javaScriptEnabled
          domStorageEnabled
          thirdPartyCookiesEnabled
          mixedContentMode="always"
          scrollEnabled={false}
          backgroundColor="transparent"
          onShouldStartLoadWithRequest={handleNavigation}
          onMessage={event => {
            setLogs(prev => [...prev, event.nativeEvent.data]);
          }}
          onError={syntheticEvent => {
            setWebviewError(JSON.stringify(syntheticEvent.nativeEvent));
          }}
          onHttpError={syntheticEvent => {
            setWebviewError('HTTP ' + JSON.stringify(syntheticEvent.nativeEvent));
          }}
        />
      </View>
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
  debugText: {
    backgroundColor: '#000',
    color: '#0f0',
    fontSize: 10,
    paddingHorizontal: 6,
    paddingVertical: 3,
    width: '100%',
    textAlign: 'left',
  },
  // רקע צהוב זמני - כדי לראות אם השטח הזה בכלל מצויר על המסך
  webviewBox: {
    width: 320,
    height: 50,
    backgroundColor: 'yellow',
  },
  webview: {
    flex: 1,
    backgroundColor: 'transparent',
  },
});
