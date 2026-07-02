import React, {useRef, useEffect, useState, useCallback} from 'react';
import {
  Alert,
  AppState,
  BackHandler,
  Linking,
  PermissionsAndroid,
  Platform,
  StatusBar,
  StyleSheet,
  View,
} from 'react-native';
import {WebView} from 'react-native-webview';
import messaging from '@react-native-firebase/messaging';

const ZOVEX_URL = 'https://davidggjg.github.io/zovex/';

// Replaced at build time by scripts/register_sha.py + CI step "Apply iOS OAuth client ID".
// iOS OAuth clients (unlike Web clients) allow custom-scheme redirect URIs, and Chrome Custom
// Tabs shares Chrome's Google session so the account picker shows saved accounts immediately.
const IOS_CLIENT_ID = 'IOS_CLIENT_ID_PLACEHOLDER';
const OAUTH_REDIRECT =
  'com.googleusercontent.apps.' +
  IOS_CLIENT_ID.replace('.apps.googleusercontent.com', '') +
  ':/oauth2redirect/google';

const CHROME_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';

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

export default function App() {
  const webviewRef = useRef(null);
  const canGoBackRef = useRef(false);
  const pendingSignIn = useRef(false);
  const [signingIn, setSigningIn] = useState(false);

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

  const handleOAuthRedirect = useCallback(
    async url => {
      if (!url || !url.startsWith('com.googleusercontent.apps.')) return;
      pendingSignIn.current = false;
      setSigningIn(false);
      const fragment = url.split('#')[1] || '';
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
      const accessToken = params.access_token;
      if (!accessToken) return;
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
    const linkingSub = Linking.addEventListener('url', event => {
      handleOAuthRedirect(event.url);
    });
    Linking.getInitialURL().then(url => {
      if (url) handleOAuthRedirect(url);
    });
    const appStateSub = AppState.addEventListener('change', state => {
      if (state === 'active' && pendingSignIn.current) {
        setTimeout(() => {
          if (pendingSignIn.current) {
            pendingSignIn.current = false;
            setSigningIn(false);
          }
        }, 1500);
      }
    });
    return () => {
      backSub.remove();
      linkingSub.remove();
      appStateSub.remove();
    };
  }, [handleOAuthRedirect]);

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

  const handleGoogleSignIn = async () => {
    if (signingIn) return;
    pendingSignIn.current = true;
    setSigningIn(true);
    try {
      const authUrl =
        'https://accounts.google.com/o/oauth2/v2/auth' +
        '?client_id=' + encodeURIComponent(IOS_CLIENT_ID) +
        '&redirect_uri=' + encodeURIComponent(OAUTH_REDIRECT) +
        '&response_type=token' +
        '&scope=' + encodeURIComponent('email profile openid') +
        '&prompt=select_account';
      await Linking.openURL(authUrl);
    } catch (e) {
      pendingSignIn.current = false;
      setSigningIn(false);
      Alert.alert('שגיאת כניסה', e.message || String(e));
    }
  };

  const onMainMsg = e => {
    try {
      const m = JSON.parse(e.nativeEvent.data);
      if (m.type === 'open' && m.url) {
        const isGoogleAuth =
          m.url.includes('accounts.google.com') ||
          m.url.includes('google.com/o/oauth2');
        if (isGoogleAuth) {
          handleGoogleSignIn();
        } else {
          Linking.openURL(m.url).catch(() => {});
        }
      }
    } catch (_) {}
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
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0a0a0a'},
  webview: {flex: 1},
});
