import React, {useRef, useState} from 'react';
import {
  BackHandler,
  Linking,
  Modal,
  StatusBar,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import {WebView} from 'react-native-webview';

const ZOVEX_URL = 'https://davidggjg.github.io/zovex/';
const ZOVEX_HOST = 'davidggjg.github.io';
const CHROME_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';

// Intercept window.open() → send URL to React Native instead of opening Chrome
const MAIN_INJECT = `(function(){
  window.open = function(url) {
    if (url) window.ReactNativeWebView.postMessage(JSON.stringify({type:'open',url:url}));
    return {closed:false,close:function(){},focus:function(){},postMessage:function(){},location:{href:url||''}};
  };
})(); true;`;

// Inside the OAuth popup WebView: fake window.opener so the callback page can
// postMessage the credential back, and intercept window.close()
const POPUP_INJECT = `(function(){
  var rn = window.ReactNativeWebView;
  Object.defineProperty(window, 'opener', {
    configurable: true,
    get: function() {
      return {
        closed: false,
        location: { origin: 'https://davidggjg.github.io' },
        postMessage: function(data, origin) {
          try {
            rn.postMessage(JSON.stringify({
              type: 'pm',
              data: typeof data === 'string' ? data : JSON.stringify(data),
              origin: origin || '*'
            }));
          } catch(e) {}
        }
      };
    }
  });
  window.close = function() {
    rn.postMessage(JSON.stringify({type:'close'}));
  };
})(); true;`;

export default function App() {
  const mainRef = useRef(null);
  const canGoBackRef = useRef(false);
  const [popupUrl, setPopupUrl] = useState(null);

  React.useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (popupUrl) {
        setPopupUrl(null);
        return true;
      }
      if (canGoBackRef.current && mainRef.current) {
        mainRef.current.goBack();
        return true;
      }
      return false;
    });
    return () => sub.remove();
  }, [popupUrl]);

  // Main WebView tells us to open a popup
  const onMainMsg = e => {
    try {
      const m = JSON.parse(e.nativeEvent.data);
      if (m.type === 'open' && m.url) setPopupUrl(m.url);
    } catch {}
  };

  // Popup WebView forwarded a postMessage — inject it into the main WebView
  const onPopupMsg = e => {
    try {
      const m = JSON.parse(e.nativeEvent.data);
      if (m.type === 'pm') {
        setPopupUrl(null);
        if (mainRef.current) {
          mainRef.current.injectJavaScript(
            `(function(){try{window.dispatchEvent(new MessageEvent('message',{` +
              `data:${JSON.stringify(m.data)},` +
              `origin:${JSON.stringify(m.origin || 'https://accounts.google.com')},` +
              `source:null` +
            `}));}catch(e){}})();true;`,
          );
        }
      } else if (m.type === 'close') {
        setPopupUrl(null);
      }
    } catch {}
  };

  // Fallback: if popup lands on our domain (OAuth callback), reload main WebView
  // with the callback URL so the site JS can process the auth result
  const onPopupNav = state => {
    if (
      state.url &&
      state.url.includes(ZOVEX_HOST) &&
      state.url !== ZOVEX_URL
    ) {
      const cbUrl = state.url;
      setPopupUrl(null);
      setTimeout(() => {
        if (mainRef.current) {
          mainRef.current.injectJavaScript(
            `window.location.href = ${JSON.stringify(cbUrl)}; true;`,
          );
        }
      }, 150);
    }
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor="#0a0a0a" />
      <WebView
        ref={mainRef}
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

      <Modal
        visible={!!popupUrl}
        animationType="slide"
        onRequestClose={() => setPopupUrl(null)}>
        <View style={styles.popup}>
          <View style={styles.bar}>
            <TouchableOpacity
              onPress={() => setPopupUrl(null)}
              style={styles.closeBtn}>
              <Text style={styles.closeText}>✕  ביטול</Text>
            </TouchableOpacity>
          </View>
          {popupUrl ? (
            <WebView
              source={{uri: popupUrl}}
              userAgent={CHROME_UA}
              javaScriptEnabled
              domStorageEnabled
              thirdPartyCookiesEnabled
              originWhitelist={['*']}
              injectedJavaScriptBeforeContentLoaded={POPUP_INJECT}
              onMessage={onPopupMsg}
              onNavigationStateChange={onPopupNav}
              style={styles.webview}
            />
          ) : null}
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0a0a0a'},
  webview: {flex: 1},
  popup: {flex: 1, backgroundColor: '#fff'},
  bar: {
    height: 52,
    backgroundColor: '#f0f0f0',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  closeBtn: {padding: 8},
  closeText: {fontSize: 16, color: '#222'},
});
