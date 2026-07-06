import React, {useState} from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';

const ADMIN_PIN = 'ZovexAdmin2026';
const REPO = 'davidggjg/zovex-android';
const WORKFLOW = 'send-notification.yml';

export default function AdminScreen({navigation}) {
  const [pin, setPin] = useState('');
  const [unlocked, setUnlocked] = useState(false);
  const [token, setToken] = useState('');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [sending, setSending] = useState(false);

  const checkPin = () => {
    if (pin === ADMIN_PIN) {
      setUnlocked(true);
    } else {
      Alert.alert('שגיאה', 'PIN שגוי');
      setPin('');
    }
  };

  const sendNotification = async () => {
    if (!token.trim()) {
      Alert.alert('שגיאה', 'הכנס GitHub Token קודם');
      return;
    }
    if (!title.trim()) {
      Alert.alert('שגיאה', 'חסרה כותרת');
      return;
    }
    if (!body.trim()) {
      Alert.alert('שגיאה', 'חסר תוכן');
      return;
    }
    setSending(true);
    try {
      const res = await fetch(
        `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
        {
          method: 'POST',
          headers: {
            Authorization: `token ${token}`,
            Accept: 'application/vnd.github.v3+json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            ref: 'main',
            inputs: {title: title.trim(), body: body.trim()},
          }),
        },
      );
      if (res.status === 204) {
        Alert.alert('הצלחה', 'ההתראה נשלחה! תגיע תוך ~30 שניות');
        setTitle('');
        setBody('');
      } else {
        const data = await res.json().catch(() => ({}));
        Alert.alert('שגיאה', data.message || `שגיאה ${res.status}`);
      }
    } catch {
      Alert.alert('שגיאה', 'שגיאת רשת');
    } finally {
      setSending(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backTxt}>✕</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>פאנל ניהול</Text>
        <View style={{width: 36}} />
      </View>

      {!unlocked ? (
        <View style={styles.pinContainer}>
          <Text style={styles.lockIcon}>🔐</Text>
          <Text style={styles.pinTitle}>ZOVEX Admin</Text>
          <Text style={styles.pinSub}>הכנס PIN כדי להמשיך</Text>
          <TextInput
            style={styles.input}
            placeholder="הכנס PIN"
            placeholderTextColor="#555"
            secureTextEntry
            value={pin}
            onChangeText={setPin}
            onSubmitEditing={checkPin}
            textAlign="right"
          />
          <TouchableOpacity style={styles.btn} onPress={checkPin}>
            <Text style={styles.btnText}>כניסה</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <ScrollView style={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.sectionTitle}>📱 שליחת התראה לכולם</Text>

          <Text style={styles.label}>GitHub Token</Text>
          <TextInput
            style={styles.input}
            placeholder="ghp_..."
            placeholderTextColor="#555"
            secureTextEntry
            value={token}
            onChangeText={setToken}
            textAlign="right"
          />

          <Text style={styles.label}>כותרת ההתראה</Text>
          <TextInput
            style={styles.input}
            placeholder="לדוגמה: עדכון חדש!"
            placeholderTextColor="#555"
            value={title}
            onChangeText={setTitle}
            maxLength={100}
            textAlign="right"
          />

          <Text style={styles.label}>תוכן ההתראה</Text>
          <TextInput
            style={[styles.input, styles.textarea]}
            placeholder="כתוב כאן את ההודעה שתישלח..."
            placeholderTextColor="#555"
            value={body}
            onChangeText={setBody}
            maxLength={300}
            multiline
            numberOfLines={4}
            textAlign="right"
            textAlignVertical="top"
          />

          <TouchableOpacity
            style={[styles.btn, sending && styles.btnDisabled]}
            onPress={sendNotification}
            disabled={sending}>
            {sending ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.btnText}>📤 שלח לכולם</Text>
            )}
          </TouchableOpacity>
        </ScrollView>
      )}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0a0a0a'},
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1a1a1a',
  },
  headerTitle: {color: '#fff', fontSize: 16, fontWeight: '700'},
  backBtn: {padding: 4},
  backTxt: {color: '#aaa', fontSize: 20},
  pinContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  lockIcon: {fontSize: 52, marginBottom: 16},
  pinTitle: {color: '#fff', fontSize: 24, fontWeight: '800', marginBottom: 4},
  pinSub: {color: '#aaa', fontSize: 14, marginBottom: 28},
  scroll: {flex: 1, padding: 16},
  sectionTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '800',
    marginBottom: 20,
    textAlign: 'center',
  },
  label: {
    color: '#aaa',
    fontSize: 12,
    fontWeight: '700',
    marginBottom: 6,
    marginTop: 14,
    textAlign: 'right',
  },
  input: {
    backgroundColor: '#1a1a1a',
    borderWidth: 1.5,
    borderColor: '#333',
    borderRadius: 12,
    padding: 12,
    color: '#fff',
    fontSize: 15,
  },
  textarea: {minHeight: 90},
  btn: {
    backgroundColor: '#e50914',
    borderRadius: 14,
    padding: 16,
    alignItems: 'center',
    marginTop: 24,
    marginBottom: 40,
  },
  btnDisabled: {opacity: 0.5},
  btnText: {color: '#fff', fontSize: 16, fontWeight: '700'},
});
