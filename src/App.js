import React, {useRef, useEffect} from 'react';
import {
  BackHandler,
  Linking,
  PermissionsAndroid,
  Platform,
  StatusBar,
  StyleSheet,
  View,
} from 'react-native';
import {WebView} from 'react-native-webview';

const ZOVEX_URL = 'https://davidggjg.github.io/zovex/';
const CHROME_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';

// When window.open() is called (Google OAuth popup), open it in real Chrome
// so the user gets the native Android account picker instead of WebView auth
const MAIN_INJECT = `(function(){
  window.open = function(url) {
    if (url) window.ReactNativeWebView.postMessage(JSON.stringify({type:'open',url:url}));
    return {closed:false,close:function(){},focus:function(){},postMessage:function(){},location:{href:url||''}};
  };
})(); true;`;

export default function App() {
  const webviewRef = useRef(null);
  const canGoBackRef = useRef(false);

  useEffect(() => {
    requestNotificationPermission();

    // Handle deep link when Chrome redirects back after OAuth
    const handleDeepLink = ({url}) => {
      if (url && url.includes('davidggjg.github.io/zovex') && webviewRef.current) {
        webviewRef.current.injectJavaScript(
          `window.location.href = ${JSON.stringify(url)}; true;`,
        );
      }
    };
    const sub = Linking.addEventListener('url', handleDeepLink);
    Linking.getInitialURL().then(url => {
      if (url) handleDeepLink({url});
    });

    const backSub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (canGoBackRef.current && webviewRef.current) {
        webviewRef.current.goBack();
        return true;
      }
      return false;
    });

    return () => {
      sub.remove();
      backSub.remove();
    };
  }, []);

  const requestNotificationPermission = async () => {
    if (Platform.OS === 'android' && Platform.Version >= 33) {
      await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS,
        {
          title: 'התראות מ-ZOVEX',
          message: 'רוצה לקבל התראות על עדכונים חשובים?',
          buttonPositive: 'אישור',
          buttonNegative: 'לא עכשיו',
        },
      );
    }
  };

  // When the site calls window.open() for Google OAuth, open Chrome
  // Chrome shows the native Android Google account picker
  const onMainMsg = e => {
    try {
      const m = JSON.parse(e.nativeEvent.data);
      if (m.type === 'open' && m.url) {
        Linking.openURL(m.url).catch(() => {});
      }
    } catch {}
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor="#0a0a0a" />
      <WebView
        ref={webviewRef}
        source={{uri: ZOVEX_URL}}
        userAgent={CHROME_UA}
        javaScriptEnabled
        domStorageEnabled
        thirdPartyCookiesEnabled
        allowsInlineMediaPlayback
        mediaPlaybackRequiresUserAction={false}
        originWhitelist={['*']}
        injectedJavaScriptBeforeContentLoaded={MAIN_INJECT}
        onMessage={onMainMsg}
        onNavigationStateChange={s => {
          canGoBackRef.current = s.canGoBack;
        }}
        onShouldStartLoadWithRequest={r => {
          if (r.url.startsWith('http://') || r.url.startsWith('https://')) {
            return true;
          }
          Linking.openURL(r.url).catch(() => {});
          return false;
        }}
        style={styles.webview}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0a0a0a'},
  webview: {flex: 1},
});
