import React, {useState} from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';

const PIN_CODE = '123456';
const LETTERS_CODE = 'zovix';

export default function AdminEntryScreen({navigation}) {
  const [pin, setPin] = useState('');
  const [letters, setLetters] = useState('');
  const [error, setError] = useState('');

  const handleEnter = () => {
    if (pin !== PIN_CODE || letters !== LETTERS_CODE) {
      setError('קוד שגוי');
      setPin('');
      setLetters('');
      return;
    }
    navigation.replace('AdminDashboard');
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <TouchableOpacity style={styles.backBtn} onPress={() => navigation.goBack()}>
        <Text style={styles.backTxt}>✕</Text>
      </TouchableOpacity>

      <View style={styles.card}>
        <Text style={styles.icon}>🔐</Text>
        <Text style={styles.title}>ZOVEX Admin</Text>
        <Text style={styles.sub}>הכנס קודי גישה</Text>

        <Text style={styles.label}>קוד PIN</Text>
        <TextInput
          style={styles.input}
          placeholder="הכנס קוד PIN"
          placeholderTextColor="#555"
          secureTextEntry
          value={pin}
          onChangeText={v => {setPin(v); setError('');}}
          keyboardType="number-pad"
          textAlign="right"
        />

        <Text style={styles.label}>קוד אותיות</Text>
        <TextInput
          style={styles.input}
          placeholder="הכנס קוד אותיות"
          placeholderTextColor="#555"
          secureTextEntry
          value={letters}
          onChangeText={v => {setLetters(v); setError('');}}
          textAlign="right"
          onSubmitEditing={handleEnter}
        />

        {!!error && <Text style={styles.error}>{error}</Text>}

        <TouchableOpacity style={styles.btn} onPress={handleEnter}>
          <Text style={styles.btnText}>כניסה לפאנל</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 28,
  },
  backBtn: {
    position: 'absolute',
    top: 20,
    right: 20,
    padding: 8,
    zIndex: 10,
  },
  backTxt: {color: '#aaa', fontSize: 20},
  card: {
    width: '100%',
    backgroundColor: '#111',
    borderRadius: 22,
    padding: 28,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#222',
  },
  icon: {fontSize: 52, marginBottom: 14},
  title: {
    color: '#fff',
    fontSize: 22,
    fontWeight: '800',
    marginBottom: 4,
  },
  sub: {color: '#666', fontSize: 13, marginBottom: 24},
  label: {
    color: '#aaa',
    fontSize: 12,
    fontWeight: '700',
    alignSelf: 'flex-end',
    marginBottom: 6,
    marginTop: 12,
  },
  input: {
    width: '100%',
    backgroundColor: '#1a1a1a',
    borderWidth: 1.5,
    borderColor: '#333',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: '#fff',
    fontSize: 15,
  },
  error: {
    color: '#ff453a',
    fontSize: 13,
    marginTop: 10,
    textAlign: 'center',
  },
  btn: {
    width: '100%',
    backgroundColor: '#e50914',
    borderRadius: 14,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 24,
  },
  btnText: {color: '#fff', fontSize: 16, fontWeight: '700'},
});
