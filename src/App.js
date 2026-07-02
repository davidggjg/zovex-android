import React, {useRef, useEffect, useState} from 'react';
import {
  Alert,
  BackHandler,
  Linking,
  Modal,
  PermissionsAndroid,
  Platform,
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

// Intercepts window.open in main WebView and forwards to React Native
const MAIN_INJECT = `(function(){
  window.open = function(url) {
    if (url) window.ReactNativeWebView.postMessage(JSON.stringify({type:'open',url:url}));
    return {
      closed: false,
      close: function(){},
      focus: function(){},
      blur: function(){},
      postMessage: function(){},
      location: {href: url || ''}
    };
  };
})(); true;`;

// Injected into the OAuth popup WebView — intercepts GIS callback to parent
const POPUP_INJECT = `(function(){
  window.opener = {
    postMessage: function(data, origin) {
      try {
        var payload = typeof data === 'string' ? data : JSON.stringify(data);
        window.ReactNativeWebView.postMessage(
          JSON.stringify({type: 'gis_token', payload: payload})
        );
      } catch(e) {}
    },
    closed: false,
    location: {href: ''},
    focus: function(){},
    blur: function(){}
  };
  window.close = function() {
    window.ReactNativeWebView.postMessage(JSON.stringify({type: 'popup_close'}));
  };
})(); true;`;

export default function App() {
  const webviewRef = useRef(null);
  const canGoBackRef = useRef(false);
  const [popupVisible, setPopupVisible] = useState(false);
  const [popupUrl, setPopupUrl] = useState('');
  const [popupKey, setPopupKey] = useState(0);

  useEffect(() => {
    setupNotifications();
    const backSub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (popupVisible) {
        setPopupVisible(false);
        return true;
      }
      if (canGoBackRef.current && webviewRef.current) {
        webviewRef.current.goBack();
        return true;
      }
      return false;
    });
    return () => backSub.remove();
  }, [popupVisible]);

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

  // After getting an OAuth access token, fetch user profile and log the user in
  const handleOAuthToken = async accessToken => {
    try {
      const resp = await fetch(
        `https://www.googleapis.com/oauth2/v2/userinfo?access_token=${encodeURIComponent(accessToken)}`,
      );
      const profile = await resp.json();
      if (!profile.email || !webviewRef.current) return;
      const userData = {
        id: profile.id || '',
        name: profile.name || '',
        email: profile.email || '',
        picture: profile.picture || '',
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
    } catch (_) {}
  };

  // Messages from the OAuth popup WebView
  const onPopupMsg = e => {
    try {
      const m = JSON.parse(e.nativeEvent.data);
      if (m.type === 'gis_token') {
        let payload = m.payload;
        if (typeof payload === 'string') {
          try {
            payload = JSON.parse(payload);
          } catch (_) {}
        }
        if (payload && payload.access_token) {
          setPopupVisible(false);
          handleOAuthToken(payload.access_token);
        }
      } else if (m.type === 'popup_close') {
        setPopupVisible(false);
      }
    } catch (_) {}
  };

  // Intercept navigation inside the OAuth popup
  const onPopupNavShouldStart = request => {
    const url = request.url;
    // Look for the OAuth callback URL which contains the access_token
    const tokenMatch = url.match(/[#&?]access_token=([^&#\s]+)/);
    if (tokenMatch) {
      const token = decodeURIComponent(tokenMatch[1]);
      setPopupVisible(false);
      handleOAuthToken(token);
      return false;
    }
    // Block non-HTTP schemes (storagerelay://, etc.)
    if (!url.startsWith('https://') && !url.startsWith('http://')) {
      setPopupVisible(false);
      return false;
    }
    return true;
  };

  // Messages from the main WebView
  const onMainMsg = e => {
    try {
      const m = JSON.parse(e.nativeEvent.data);
      if (m.type === 'open' && m.url) {
        const isGoogleAuth =
          m.url.includes('accounts.google.com') ||
          m.url.includes('google.com/o/oauth2');
        if (isGoogleAuth) {
          setPopupUrl(m.url);
          setPopupKey(k => k + 1);
          setPopupVisible(true);
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

      <Modal
        visible={popupVisible}
        animationType="slide"
        onRequestClose={() => setPopupVisible(false)}>
        <View style={styles.popupContainer}>
          <View style={styles.popupHeader}>
            <Text style={styles.popupTitle}>התחברות עם Google</Text>
            <TouchableOpacity
              onPress={() => setPopupVisible(false)}
              hitSlop={{top: 10, bottom: 10, left: 10, right: 10}}>
              <Text style={styles.closeBtn}>✕</Text>
            </TouchableOpacity>
          </View>
          {popupUrl ? (
            <WebView
              key={popupKey}
              source={{uri: popupUrl}}
              userAgent={CHROME_UA}
              javaScriptEnabled
              domStorageEnabled
              thirdPartyCookiesEnabled
              injectedJavaScriptBeforeContentLoaded={POPUP_INJECT}
              onMessage={onPopupMsg}
              onShouldStartLoadWithRequest={onPopupNavShouldStart}
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
  popupContainer: {flex: 1, backgroundColor: '#fff'},
  popupHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    paddingTop: Platform.OS === 'android' ? 12 : 48,
    backgroundColor: '#f5f5f5',
    borderBottomWidth: 1,
    borderBottomColor: '#ddd',
  },
  popupTitle: {fontSize: 16, fontWeight: '600', color: '#333'},
  closeBtn: {fontSize: 22, color: '#555', paddingHorizontal: 4},
});
