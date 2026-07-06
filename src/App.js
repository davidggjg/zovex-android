import React, {useRef, useEffect, useState, useCallback} from 'react';
import {
  Alert,
  AppState,
  BackHandler,
  Linking,
  NativeModules,
  PermissionsAndroid,
  Platform,
  StatusBar,
  StyleSheet,
  View,
} from 'react-native';
import {WebView} from 'react-native-webview';
import messaging from '@react-native-firebase/messaging';

const {PipModule} = NativeModules;

const ZOVEX_URL = 'https://davidggjg.github.io/zovex/';

// Replaced at build time by scripts/register_sha.py + "Apply iOS OAuth client ID" CI step.
// iOS OAuth clients allow custom-scheme redirect URIs (unlike web clients).
// Chrome Custom Tabs shares Chrome's Google session → account picker with no credentials.
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

// ── Pure-JS SHA-256 for PKCE ─────────────────────────────────────────────────
// Runs in Hermes without any native crypto module.
function sha256bytes(msg) {
  const K = new Uint32Array([
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
  ]);
  // UTF-8 encode (code verifier is ASCII, but be safe)
  const bytes = [];
  for (let i = 0; i < msg.length; i++) {
    const c = msg.charCodeAt(i);
    if (c < 0x80) { bytes.push(c); }
    else if (c < 0x800) { bytes.push((c >> 6) | 0xc0, (c & 0x3f) | 0x80); }
    else { bytes.push((c >> 12) | 0xe0, ((c >> 6) & 0x3f) | 0x80, (c & 0x3f) | 0x80); }
  }
  const L = bytes.length;
  bytes.push(0x80);
  while ((bytes.length % 64) !== 56) bytes.push(0);
  const bits = L * 8;
  bytes.push(0, 0, 0, 0, (bits >>> 24) & 0xff, (bits >>> 16) & 0xff, (bits >>> 8) & 0xff, bits & 0xff);

  const H = new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
  const W = new Uint32Array(64);
  for (let i = 0; i < bytes.length; i += 64) {
    for (let j = 0; j < 16; j++) {
      W[j] = ((bytes[i+j*4]<<24)|(bytes[i+j*4+1]<<16)|(bytes[i+j*4+2]<<8)|bytes[i+j*4+3]) >>> 0;
    }
    for (let j = 16; j < 64; j++) {
      const s0 = (((W[j-15]>>>7)|(W[j-15]<<25))^((W[j-15]>>>18)|(W[j-15]<<14))^(W[j-15]>>>3)) >>> 0;
      const s1 = (((W[j-2]>>>17)|(W[j-2]<<15))^((W[j-2]>>>19)|(W[j-2]<<13))^(W[j-2]>>>10)) >>> 0;
      W[j] = (W[j-16]+s0+W[j-7]+s1) >>> 0;
    }
    let a=H[0], b=H[1], c=H[2], d=H[3], e=H[4], f=H[5], g=H[6], h=H[7];
    for (let j = 0; j < 64; j++) {
      const S1 = (((e>>>6)|(e<<26))^((e>>>11)|(e<<21))^((e>>>25)|(e<<7))) >>> 0;
      const ch = ((e & f) ^ (~e & g)) >>> 0;
      const t1 = (h + S1 + ch + K[j] + W[j]) >>> 0;
      const S0 = (((a>>>2)|(a<<30))^((a>>>13)|(a<<19))^((a>>>22)|(a<<10))) >>> 0;
      const maj = ((a & b) ^ (a & c) ^ (b & c)) >>> 0;
      const t2 = (S0 + maj) >>> 0;
      h=g; g=f; f=e; e=(d+t1)>>>0; d=c; c=b; b=a; a=(t1+t2)>>>0;
    }
    H[0]=(H[0]+a)>>>0; H[1]=(H[1]+b)>>>0; H[2]=(H[2]+c)>>>0; H[3]=(H[3]+d)>>>0;
    H[4]=(H[4]+e)>>>0; H[5]=(H[5]+f)>>>0; H[6]=(H[6]+g)>>>0; H[7]=(H[7]+h)>>>0;
  }
  const out = [];
  for (let i = 0; i < 8; i++) {
    out.push((H[i]>>>24)&0xff, (H[i]>>>16)&0xff, (H[i]>>>8)&0xff, H[i]&0xff);
  }
  return out;
}

function base64urlEncodeBytes(bytes) {
  const t = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  let r = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i], b1 = bytes[i+1] || 0, b2 = bytes[i+2] || 0;
    r += t[b0 >> 2] + t[((b0 & 3) << 4) | (b1 >> 4)];
    if (i + 1 < bytes.length) r += t[((b1 & 15) << 2) | (b2 >> 6)];
    if (i + 2 < bytes.length) r += t[b2 & 63];
  }
  return r;
}

function generateCodeVerifier() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';
  let v = '';
  for (let i = 0; i < 128; i++) v += chars[Math.floor(Math.random() * chars.length)];
  return v;
}
// ─────────────────────────────────────────────────────────────────────────────

export default function App() {
  const webviewRef = useRef(null);
  const canGoBackRef = useRef(false);
  const pendingSignIn = useRef(false);
  const codeVerifierRef = useRef(null);
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

      // Authorization code flow: code arrives in the query string (?code=CODE)
      const qIdx = url.indexOf('?');
      if (qIdx === -1) return;
      const params = {};
      url.slice(qIdx + 1).split('&').forEach(pair => {
        const eq = pair.indexOf('=');
        if (eq > -1) {
          try {
            params[decodeURIComponent(pair.slice(0, eq))] = decodeURIComponent(pair.slice(eq + 1));
          } catch (_) {}
        }
      });

      const authCode = params.code;
      const savedVerifier = codeVerifierRef.current;
      codeVerifierRef.current = null;
      if (!authCode || !savedVerifier) return;

      try {
        // Exchange code for access_token using PKCE (no client_secret needed for native apps)
        const tokenRes = await fetch('https://oauth2.googleapis.com/token', {
          method: 'POST',
          headers: {'Content-Type': 'application/x-www-form-urlencoded'},
          body:
            'code=' + encodeURIComponent(authCode) +
            '&client_id=' + encodeURIComponent(IOS_CLIENT_ID) +
            '&redirect_uri=' + encodeURIComponent(OAUTH_REDIRECT) +
            '&code_verifier=' + encodeURIComponent(savedVerifier) +
            '&grant_type=authorization_code',
        });
        const tokenData = await tokenRes.json();
        if (!tokenData.access_token) {
          throw new Error(tokenData.error_description || tokenData.error || 'No access_token in response');
        }

        const userRes = await fetch('https://www.googleapis.com/oauth2/v2/userinfo', {
          headers: {Authorization: 'Bearer ' + tokenData.access_token},
        });
        const user = await userRes.json();
        injectGoogleUser(
          {id: user.id || '', name: user.name || '', email: user.email || '', picture: user.picture || ''},
          tokenData.access_token,
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
            codeVerifierRef.current = null;
          }
        }, 1500);
      }
      if (state === 'background' && videoPlayingRef.current) {
        // Override document.hidden so the video player doesn't pause on background
        webviewRef.current?.injectJavaScript(`
          (function(){
            try {
              Object.defineProperty(document,'visibilityState',{get:()=>'visible',configurable:true});
              Object.defineProperty(document,'hidden',{get:()=>false,configurable:true});
              var v=document.querySelector('video');
              if(v&&v.paused){v.play().catch(()=>{});}
            }catch(e){}
          })(); true;
        `);
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
    const codeVerifier = generateCodeVerifier();
    const codeChallenge = base64urlEncodeBytes(sha256bytes(codeVerifier));
    codeVerifierRef.current = codeVerifier;
    pendingSignIn.current = true;
    setSigningIn(true);
    try {
      const authUrl =
        'https://accounts.google.com/o/oauth2/v2/auth' +
        '?client_id=' + encodeURIComponent(IOS_CLIENT_ID) +
        '&redirect_uri=' + encodeURIComponent(OAUTH_REDIRECT) +
        '&response_type=code' +
        '&scope=' + encodeURIComponent('email profile openid') +
        '&code_challenge=' + encodeURIComponent(codeChallenge) +
        '&code_challenge_method=S256' +
        '&prompt=select_account';
      await Linking.openURL(authUrl);
    } catch (e) {
      pendingSignIn.current = false;
      setSigningIn(false);
      codeVerifierRef.current = null;
      Alert.alert('שגיאת כניסה', e.message || String(e));
    }
  };

  const videoPlayingRef = useRef(false);

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
      } else if (m.type === 'player_open') {
        // Hide both status bar + nav bar for immersive player
        PipModule?.setFullscreen(!!m.value);
        if (!m.value) StatusBar.setBarStyle('light-content', true);
      } else if (m.type === 'fullscreen') {
        // Fullscreen button tapped inside player
        PipModule?.setFullscreen(!!m.enter);
      } else if (m.type === 'video_playing') {
        const playing = !!m.value;
        videoPlayingRef.current = playing;
        PipModule?.setVideoPlaying(playing);
        if (!playing) {
          PipModule?.setFullscreen(false);
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
        injectedJavaScriptBeforeContentLoadedForMainFrameOnly={false}
        injectedJavaScriptForMainFrameOnly={false}
        onMessage={onMainMsg}
        onMessageForMainFrameOnly={false}
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
