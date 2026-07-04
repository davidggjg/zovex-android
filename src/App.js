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

const APP_VERSION = '1.0';
const DIALOG_CONFIG_URL =
  'https://raw.githubusercontent.com/davidggjg/zovex-android/main/public/dialog.json';

const Stack = createNativeStackNavigator();

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
