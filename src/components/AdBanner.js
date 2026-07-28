import React, {useState} from 'react';
import {View, Text, StyleSheet, Linking} from 'react-native';
import {WebView} from 'react-native-webview';

const AD_BASE_URL = 'https://davidggjg.github.io/zovex/';

// שתי בעיות שונות שמודעות מובייל אוהבות לעשות בתוך WebView:
// 1. deep-link לאפליקציה (aliexpress:// / market:// / intent://) - ה-WebView
//    לא יודע לנווט לזה בעצמו וקורס עם ERR_UNKNOWN_URL_SCHEME.
// 2. "השתלטות" על העמוד הראשי - במקום לטעון את קריאייטיב המודעה בתוך
//    ה-iframe הפנימי שלה, המודעה מנווטת את כל ה-WebView (הבאנר הקטן
//    שלנו, 320x50) לאתר יעד שלם (למשל AliExpress), מה שיהפוך את הבאנר
//    לרינדור מכווץ ומכוער של אתר מלא.
// שתי הבעיות מטופלות באותה פונקציה: ניווט http(s) שהוא top-frame (לא
// iframe פנימי של המודעה עצמה) ומחוץ לדף הבסיס שלנו - נפתח ב-OS/דפדפן
// חיצוני במקום בתוך הבאנר. כל שאר הניווטים (iframe-ים פנימיים של קוד
// המודעה עצמו) מותרים כרגיל, אחרת המודעה לא תיטען בכלל.
function handleNavigation(request) {
  const {url, isTopFrame} = request;
  const isHttp = /^https?:/i.test(url);
  if (isHttp && (!isTopFrame || url === AD_BASE_URL)) return true;
  // כל השאר (ניווט top-frame לאתר יעד, או סכימת deep-link לאפליקציה) -
  // נפתח ב-OS/דפדפן חיצוני. openURL נכשל בשקט אם אין אפליקציה שתטפל בזה.
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
