import React, {useRef} from 'react';
import {BackHandler, Linking, StatusBar, StyleSheet, View} from 'react-native';
import {WebView} from 'react-native-webview';

const ZOVEX_URL = 'https://davidggjg.github.io/zovex/';

const CHROME_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';

// Convert window.open() popups (used by Google OAuth) into same-window navigation
// so the auth flow stays inside the WebView instead of opening Chrome
const INJECT_BEFORE = `
  (function() {
    window.open = function(url) {
      if (url) { window.location.href = url; }
      return {
        closed: false,
        close: function() {},
        focus: function() {},
        postMessage: function() {},
        location: { href: url || '' },
      };
    };
  })();
  true;
`;

export default function App() {
  const webviewRef = useRef(null);
  const canGoBackRef = useRef(false);

  React.useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (canGoBackRef.current && webviewRef.current) {
        webviewRef.current.goBack();
        return true;
      }
      return false;
    });
    return () => sub.remove();
  }, []);

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
        injectedJavaScriptBeforeContentLoaded={INJECT_BEFORE}
        onShouldStartLoadWithRequest={request => {
          if (
            request.url.startsWith('http://') ||
            request.url.startsWith('https://')
          ) {
            return true;
          }
          Linking.openURL(request.url).catch(() => {});
          return false;
        }}
        onNavigationStateChange={state => {
          canGoBackRef.current = state.canGoBack;
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
