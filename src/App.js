import React, {useRef} from 'react';
import {BackHandler, StatusBar, StyleSheet, View} from 'react-native';
import {WebView} from 'react-native-webview';

const ZOVEX_URL = 'https://davidggjg.github.io/zovex/';

// Chrome user agent without "wv" marker so Google OAuth isn't blocked in WebView
const CHROME_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';

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
