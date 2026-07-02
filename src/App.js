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
  '537028202942-tra1klpqsbu6uo475gshp5r43m68h47m.apps.googleusercontent.com';

const CHROME_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';

// Intercept window.open() so native Google Sign-In handles it instead of Chrome
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
      // Inject FCM token into the WebView so the website can save it
      injectFcmToken(token);
    }

    // Handle notifications received while app is in foreground
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

  // Native Google Sign-In — triggered when window.open() is intercepted
  const handleNativeGoogleSignIn = async () => {
    if (signingIn) return;
    setSigningIn(true);
    try {
      await GoogleSignin.hasPlayServices();
      const userInfo = await GoogleSignin.signIn();
      const {idToken} = await GoogleSignin.getTokens();

      if (webviewRef.current && idToken) {
        // Try to sign in via Firebase Auth (if the website uses it)
        // Also dispatch a custom event the website can listen to
        webviewRef.current.injectJavaScript(`
          (function(){
            var token = ${JSON.stringify(idToken)};
            var email = ${JSON.stringify(userInfo.data?.user?.email || '')};
            var name = ${JSON.stringify(userInfo.data?.user?.name || '')};
            var photo = ${JSON.stringify(userInfo.data?.user?.photo || '')};

            // Firebase Auth compat
            if (window.firebase && window.firebase.auth) {
              var cred = window.firebase.auth.GoogleAuthProvider.credential(token);
              window.firebase.auth().signInWithCredential(cred).catch(function(){});
            }

            // Firebase Auth modular (v9+)
            if (window.__firebaseAuth) {
              try {
                var GoogleAuthProvider = window.__firebaseGoogleProvider || {};
                var credential = {providerId:'google.com', signInMethod:'google.com', idToken: token};
                window.__firebaseAuth.signInWithCredential && window.__firebaseAuth.signInWithCredential(credential).catch(function(){});
              } catch(e){}
            }

            // GIS / custom callback
            ['handleCredentialResponse','onGoogleSignIn','googleCallback'].forEach(function(fn){
              if (typeof window[fn] === 'function') {
                try { window[fn]({credential: token}); } catch(e){}
              }
            });

            // Custom native event — website can listen with: window.addEventListener('nativeGoogleSignIn', ...)
            window.dispatchEvent(new CustomEvent('nativeGoogleSignIn', {
              detail: {idToken: token, email: email, name: name, photo: photo}
            }));

            // Simulate postMessage from Google accounts (for Firebase popup flow)
            window.dispatchEvent(new MessageEvent('message', {
              data: JSON.stringify({credential: token}),
              origin: 'https://accounts.google.com',
              source: null
            }));
          })();
          true;
        `);
      }
    } catch (e) {
      // User cancelled or error — silently ignore
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
          // Inject FCM token on each new page load
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
