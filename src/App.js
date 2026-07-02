import React, {useRef, useEffect, useState, useCallback} from 'react';
import {
  Alert,
  BackHandler,
  Linking,
  Modal,
  PermissionsAndroid,
  Platform,
  SafeAreaView,
  StatusBar,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import {WebView} from 'react-native-webview';
import messaging from '@react-native-firebase/messaging';

const ZOVEX_URL = 'https://davidggjg.github.io/zovex/';
const CHROME_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';

// Intercepts window.open so the Google OAuth popup URL reaches native code
const MAIN_INJECT = `(function(){
  window.open = function(url) {
    if (url) window.ReactNativeWebView.postMessage(JSON.stringify({type:'open',url:url}));
    return {closed:false,close:function(){},focus:function(){},blur:function(){},postMessage:function(){},location:{href:url||''}};
  };
  window.__gisCallback = null;
  (function pollGIS() {
    try {
      if (window.google && window.google.accounts && window.google.accounts.oauth2 && window.google.accounts.oauth2.initTokenClient) {
        var orig = window.google.accounts.oauth2.initTokenClient.bind(window.google.accounts.oauth2);
        window.google.accounts.oauth2.initTokenClient = function(cfg) {
          window.__gisCallback = cfg && cfg.callback;
          return orig(cfg);
        };
      } else {
        setTimeout(pollGIS, 150);
      }
    } catch(e) { setTimeout(pollGIS, 150); }
  })();
})(); true;`;

// Injected into the sign-in popup WebView — fakes window.opener so GIS postMessage reaches us
const POPUP_INJECT = `(function(){
  try {
    Object.defineProperty(window, 'opener', {
      get: function() {
        return {
          postMessage: function(data, targetOrigin) {
            if (window.ReactNativeWebView) {
              window.ReactNativeWebView.postMessage(JSON.stringify({
                type: 'popup_msg',
                data: typeof data === 'string' ? data : JSON.stringify(data),
                origin: window.location.origin
              }));
            }
          },
          closed: false,
          location: {href: ''}
        };
      },
      configurable: true,
      enumerable: true
    });
  } catch(e) {}
})(); true;`;

export default function App() {
  const webviewRef = useRef(null);
  const canGoBackRef = useRef(false);
  const [popupUrl, setPopupUrl] = useState(null);

  const injectGoogleUser = useCallback((userData, accessToken) => {
    if (!webviewRef.current) return;
    const userJson = JSON.stringify(JSON.stringify(userData));
    const tokenJson = JSON.stringify(accessToken || '');
    webviewRef.current.injectJavaScript(`
      (function(){
        try {
          localStorage.setItem('zovex_user', ${userJson});
          localStorage.removeItem('zovex_skipped');
          if (window.__gisCallback && ${tokenJson}) {
            window.__gisCallback({
              access_token: ${tokenJson},
              token_type: 'Bearer',
              expires_in: 3599,
              scope: 'email profile openid',
              authuser: '0',
              prompt: 'select_account'
            });
          } else {
            window.location.reload();
          }
        } catch(e) { window.location.reload(); }
      })(); true;
    `);
  }, []);

  const handleAccessToken = useCallback(
    async accessToken => {
      try {
        const res = await fetch('https://www.googleapis.com/oauth2/v2/userinfo', {
          headers: {Authorization: 'Bearer ' + accessToken},
        });
        const user = await res.json();
        injectGoogleUser(
          {
            id: user.id || '',
            name: user.name || '',
            email: user.email || '',
            picture: user.picture || '',
          },
          accessToken,
        );
      } catch (e) {
        Alert.alert('שגיאת כניסה', e.message || String(e));
      }
    },
    [injectGoogleUser],
  );

  useEffect(() => {
    setupNotifications();
    const backSub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (canGoBackRef.current && webviewRef.current) {
        webviewRef.current.goBack();
        return true;
      }
      return false;
    });
    return () => backSub.remove();
  }, []);

  const setupNotifications = async () => {
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
    const authStatus = await messaging().requestPermission();
    const enabled =
      authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
      authStatus === messaging.AuthorizationStatus.PROVISIONAL;
    if (enabled) {
      const token = await messaging().getToken();
      injectFcmToken(token);
      messaging().subscribeToTopic('allUsers').catch(() => {});
    }
    messaging().onMessage(async remoteMessage => {
      if (remoteMessage.notification) {
        Alert.alert(
          remoteMessage.notification.title || 'ZOVEX',
          remoteMessage.notification.body || '',
        );
      }
    });
  };

  const injectFcmToken = token => {
    if (!webviewRef.current || !token) return;
    webviewRef.current.injectJavaScript(`
      window.dispatchEvent(new CustomEvent('fcmToken', {detail: ${JSON.stringify(token)}}));
      if (typeof window.onFcmToken === 'function') window.onFcmToken(${JSON.stringify(token)});
      true;
    `);
  };

  const onMainMsg = e => {
    try {
      const m = JSON.parse(e.nativeEvent.data);
      if (m.type === 'open' && m.url) {
        const isGoogleAuth =
          m.url.includes('accounts.google.com') ||
          m.url.includes('google.com/o/oauth2');
        if (isGoogleAuth) {
          setPopupUrl(m.url);
        } else {
          Linking.openURL(m.url).catch(() => {});
        }
      }
    } catch (_) {}
  };

  // Receives window.opener.postMessage from the popup WebView and relays it to the main WebView
  const onPopupMsg = useCallback(
    e => {
      try {
        const m = JSON.parse(e.nativeEvent.data);
        if (m.type === 'popup_msg') {
          setPopupUrl(null);
          if (webviewRef.current) {
            const dataJson = JSON.stringify(m.data);
            const originJson = JSON.stringify(
              m.origin || 'https://accounts.google.com',
            );
            webviewRef.current.injectJavaScript(`
              (function(){
                try {
                  window.dispatchEvent(new MessageEvent('message', {
                    data: ${dataJson},
                    origin: ${originJson},
                    source: window,
                    bubbles: false,
                    cancelable: false
                  }));
                } catch(er){}
              })(); true;
            `);
          }
        }
      } catch (_) {}
    },
    [],
  );

  // Catches non-http redirects in the popup (e.g. storagerelay://) which carry the access_token
  const onPopupShouldLoad = useCallback(
    req => {
      if (req.url.startsWith('http://') || req.url.startsWith('https://')) {
        return true;
      }
      setPopupUrl(null);
      const fragment = req.url.split('#')[1] || '';
      const params = {};
      fragment.split('&').forEach(pair => {
        const eq = pair.indexOf('=');
        if (eq > -1) {
          try {
            params[decodeURIComponent(pair.slice(0, eq))] = decodeURIComponent(
              pair.slice(eq + 1),
            );
          } catch (_) {}
        }
      });
      if (params.access_token) {
        handleAccessToken(params.access_token);
      }
      return false;
    },
    [handleAccessToken],
  );

  // Also watch navigation state of popup for access_token in any URL format
  const onPopupNavChange = useCallback(
    nav => {
      if (nav.url && nav.url.includes('access_token=') && popupUrl) {
        setPopupUrl(null);
        const part = nav.url.split('#')[1] || nav.url.split('?')[1] || '';
        const params = {};
        part.split('&').forEach(pair => {
          const eq = pair.indexOf('=');
          if (eq > -1) {
            try {
              params[decodeURIComponent(pair.slice(0, eq))] =
                decodeURIComponent(pair.slice(eq + 1));
            } catch (_) {}
          }
        });
        if (params.access_token) {
          handleAccessToken(params.access_token);
        }
      }
    },
    [handleAccessToken, popupUrl],
  );

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
          if (s.loading === false) {
            messaging().getToken().then(injectFcmToken).catch(() => {});
          }
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
      {popupUrl ? (
        <Modal
          visible
          animationType="slide"
          statusBarTranslucent
          onRequestClose={() => setPopupUrl(null)}>
          <SafeAreaView style={styles.popupContainer}>
            <WebView
              source={{uri: popupUrl}}
              userAgent={CHROME_UA}
              javaScriptEnabled
              domStorageEnabled
              thirdPartyCookiesEnabled
              injectedJavaScriptBeforeContentLoaded={POPUP_INJECT}
              onMessage={onPopupMsg}
              onShouldStartLoadWithRequest={onPopupShouldLoad}
              onNavigationStateChange={onPopupNavChange}
              style={styles.webview}
            />
            <TouchableOpacity
              style={styles.cancelBtn}
              onPress={() => setPopupUrl(null)}>
              <Text style={styles.cancelText}>ביטול</Text>
            </TouchableOpacity>
          </SafeAreaView>
        </Modal>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0a0a0a'},
  webview: {flex: 1},
  popupContainer: {flex: 1, backgroundColor: '#fff'},
  cancelBtn: {padding: 16, backgroundColor: '#f0f0f0', alignItems: 'center'},
  cancelText: {fontSize: 16, color: '#333'},
});
