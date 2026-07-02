import React, {useRef, useEffect, useState} from 'react';
import {
  Alert,
  BackHandler,
  Linking,
  PermissionsAndroid,
  Platform,
  StatusBar,
  StyleSheet,
  View,
} from 'react-native';
import {WebView} from 'react-native-webview';
import {GoogleSignin} from '@react-native-google-signin/google-signin';
import messaging from '@react-native-firebase/messaging';

const ZOVEX_URL = 'https://davidggjg.github.io/zovex/';
const WEB_CLIENT_ID =
  '1095467813314-d3fn8ad1roao5qk3gtilg9hhq8drn85v.apps.googleusercontent.com';

const CHROME_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';

const MAIN_INJECT = `(function(){
  window.open = function(url) {
    if (url) window.ReactNativeWebView.postMessage(JSON.stringify({type:'open',url:url}));
    return {closed:false,close:function(){},focus:function(){},postMessage:function(){},location:{href:url||''}};
  };
})(); true;`;

GoogleSignin.configure({webClientId: WEB_CLIENT_ID, offlineAccess: false});

export default function App() {
  const webviewRef = useRef(null);
  const canGoBackRef = useRef(false);
  const [signingIn, setSigningIn] = useState(false);

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
      // Subscribe to broadcast topic so admin can send to all users at once
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

  // Native Google Sign-In — triggered when window.open() is intercepted for accounts.google.com
  // The website uses GIS (window.google.accounts.oauth2.initTokenClient) and stores
  // the signed-in user as { id, name, email, picture } in localStorage['zovex_user'].
  // We bypass the GIS popup entirely: sign in natively, then set localStorage directly
  // and reload so the website picks up the session.
  const handleNativeGoogleSignIn = async () => {
    if (signingIn) return;
    setSigningIn(true);
    try {
      await GoogleSignin.hasPlayServices();
      const result = await GoogleSignin.signIn();
      const user = result?.data?.user || result?.user;
      if (!user || !webviewRef.current) return;

      const userData = {
        id: user.id || '',
        name: user.name || '',
        email: user.email || '',
        picture: user.photo || '',
      };
      const userJson = JSON.stringify(JSON.stringify(userData));

      webviewRef.current.injectJavaScript(`
        (function(){
          try {
            localStorage.setItem('zovex_user', ${userJson});
            localStorage.removeItem('zovex_skipped');
            window.location.reload();
          } catch(e) {}
        })(); true;
      `);
    } catch (e) {
      // Cancelled or error — silent
    } finally {
      setSigningIn(false);
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
          handleNativeGoogleSignIn();
        } else {
          Linking.openURL(m.url).catch(() => {});
        }
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
          if (s.loading === false) {
            messaging()
              .getToken()
              .then(injectFcmToken)
              .catch(() => {});
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
