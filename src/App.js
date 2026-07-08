import React, {useEffect, useRef, useState} from 'react';
import {
  Alert,
  Animated,
  Easing,
  Linking,
  PermissionsAndroid,
  Platform,
  StatusBar,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import {NavigationContainer} from '@react-navigation/native';
import {createNativeStackNavigator} from '@react-navigation/native-stack';
import messaging from '@react-native-firebase/messaging';
import HomeScreen from './screens/HomeScreen';
import PlayerScreen from './screens/PlayerScreen';
import SeriesScreen from './screens/SeriesScreen';
import AdminScreen from './screens/AdminScreen';
import AdminEntryScreen from './screens/AdminEntryScreen';
import AdminDashboardScreen from './screens/AdminDashboardScreen';
import {initUserId} from './api/userStore';

const Stack = createNativeStackNavigator();

const APP_VERSION = '1.0';
const DIALOG_CONFIG_URL =
  'https://raw.githubusercontent.com/davidggjg/zovex-android/main/public/dialog.json';

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
  const [appReady, setAppReady] = useState(false);
  const [dialogConfig, setDialogConfig] = useState(null);
  const glowAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    let timer;
    const boot = async () => {
      await initUserId();
      try {
        const controller = new AbortController();
        timer = setTimeout(() => {
          controller.abort();
          setAppReady(true);
        }, 3000);
        const res = await fetch(DIALOG_CONFIG_URL + '?_t=' + Date.now(), {
          signal: controller.signal,
        });
        clearTimeout(timer);
        const cfg = await res.json();
        if (cfg?.active === true) {
          const versions = Array.isArray(cfg.target_versions)
            ? cfg.target_versions
            : [];
          if (versions.length === 0 || versions.includes(APP_VERSION)) {
            setDialogConfig(cfg);
          }
        }
      } catch (_) {
        clearTimeout(timer);
      }
      setAppReady(true);
    };
    boot();
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!dialogConfig) return;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(glowAnim, {
          toValue: 1,
          duration: 1300,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: false,
        }),
        Animated.timing(glowAnim, {
          toValue: 0,
          duration: 1300,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: false,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [dialogConfig, glowAnim]);

  useEffect(() => {
    setupNotifications();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    try {
      const authStatus = await messaging().requestPermission();
      const enabled =
        authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
        authStatus === messaging.AuthorizationStatus.PROVISIONAL;
      if (enabled) {
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
    } catch (_) {}
  };

  const borderColor = glowAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ['rgba(180,0,0,0.25)', 'rgba(255,55,55,0.95)'],
  });
  const glowLayerOpacity = glowAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [0.02, 0.2],
  });

  if (!appReady) {
    return (
      <View style={styles.splash}>
        <StatusBar barStyle="light-content" backgroundColor="#0a0a0a" />
        <Text style={styles.splashText}>ZOVEX</Text>
      </View>
    );
  }

  if (dialogConfig) {
    return (
      <View style={styles.dialogOverlay}>
        <StatusBar barStyle="light-content" backgroundColor="#000" />
        <Animated.View style={[styles.dialogCard, {borderColor}]}>
          <Animated.View
            style={[styles.dialogGlowLayer, {opacity: glowLayerOpacity}]}
          />
          <Text style={styles.dialogBadge}>⚡ ZOVEX</Text>
          <Text style={styles.dialogTitle}>
            {dialogConfig.title || 'עדכון זמין'}
          </Text>
          <Text style={styles.dialogMessage}>{dialogConfig.message || ''}</Text>
          <View style={styles.dialogButtons}>
            <TouchableOpacity
              style={styles.dialogBtnJoin}
              activeOpacity={0.75}
              onPress={() => {
                const u = dialogConfig.join_url;
                if (u) Linking.openURL(u).catch(() => {});
              }}>
              <Text style={styles.dialogBtnText}>הצטרפו</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.dialogBtnUpdate}
              activeOpacity={0.75}
              onPress={() => {
                const u = dialogConfig.update_url;
                if (u) Linking.openURL(u).catch(() => {});
              }}>
              <Text style={styles.dialogBtnText}>עדכון עכשיו</Text>
            </TouchableOpacity>
          </View>
        </Animated.View>
      </View>
    );
  }

  return (
    <NavigationContainer>
      <StatusBar barStyle="light-content" backgroundColor="#0a0a0a" />
      <Stack.Navigator screenOptions={{headerShown: false}}>
        <Stack.Screen name="Home" component={HomeScreen} />
        <Stack.Screen name="Player" component={PlayerScreen} />
        <Stack.Screen name="Series" component={SeriesScreen} />
        <Stack.Screen name="Admin" component={AdminScreen} />
        <Stack.Screen name="AdminEntry" component={AdminEntryScreen} />
        <Stack.Screen name="AdminDashboard" component={AdminDashboardScreen} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#0a0a0a',
  },
  splashText: {
    color: '#cc1111',
    fontSize: 36,
    fontWeight: '900',
    letterSpacing: 8,
  },
  dialogOverlay: {
    flex: 1,
    backgroundColor: '#000',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 24,
  },
  dialogCard: {
    width: '100%',
    maxWidth: 370,
    backgroundColor: '#0d0d0d',
    borderRadius: 22,
    borderWidth: 2,
    paddingHorizontal: 28,
    paddingVertical: 32,
    alignItems: 'center',
    elevation: 28,
    overflow: 'hidden',
  },
  dialogGlowLayer: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: '#ff1c1c',
  },
  dialogBadge: {
    color: '#ff4040',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 5,
    marginBottom: 18,
    textAlign: 'center',
  },
  dialogTitle: {
    color: '#ffffff',
    fontSize: 22,
    fontWeight: '800',
    textAlign: 'center',
    marginBottom: 12,
    lineHeight: 30,
  },
  dialogMessage: {
    color: '#aaaaaa',
    fontSize: 15,
    textAlign: 'center',
    lineHeight: 24,
    marginBottom: 28,
  },
  dialogButtons: {
    flexDirection: 'row',
    width: '100%',
  },
  dialogBtnJoin: {
    flex: 1,
    backgroundColor: '#1a1a1a',
    borderWidth: 1,
    borderColor: '#333',
    borderRadius: 13,
    paddingVertical: 14,
    alignItems: 'center',
    marginRight: 8,
  },
  dialogBtnUpdate: {
    flex: 1,
    backgroundColor: '#c01010',
    borderRadius: 13,
    paddingVertical: 14,
    alignItems: 'center',
  },
  dialogBtnText: {
    color: '#ffffff',
    fontSize: 15,
    fontWeight: '700',
    textAlign: 'center',
  },
});
