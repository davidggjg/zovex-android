// ─────────────────────────────────────────────────────────────────────────────
// ZOVEX · מסך תמיכה בתוך האפליקציה. מחליף את הפתיחה הישירה של טלגרם:
// המשתמש יכול לכתוב לנו צ'אט (תמיכה / חוות דעת / טיפ), המנהל רואה בפאנל ומגיב,
// והתשובה מופיעה כאן. כפתור טלגרם נשאר כאופציה.
// ─────────────────────────────────────────────────────────────────────────────
import React, {useEffect, useState, useRef, useCallback} from 'react';
import {
  View, Text, Modal, TouchableOpacity, TextInput, ScrollView,
  StyleSheet, Linking, ActivityIndicator, KeyboardAvoidingView, Platform,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {sendFeedback, fetchMyFeedback} from '../api/movies';

const DEVICE_ID_KEY = 'zovex_device_id';
const KINDS = [
  {k: 'support', label: 'תמיכה 💬'},
  {k: 'review', label: 'חוות דעת ⭐'},
  {k: 'tip', label: 'טיפ 💡'},
];

// מזהה יציב למשתמש: אם מחובר לגוגל → email; אחרת מזהה מכשיר אקראי ששמור מקומית.
async function resolveUserId(user) {
  if (user && user.email) return 'g:' + user.email;
  let id = await AsyncStorage.getItem(DEVICE_ID_KEY).catch(() => null);
  if (!id) {
    id = 'd:' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    await AsyncStorage.setItem(DEVICE_ID_KEY, id).catch(() => {});
  }
  return id;
}

export default function SupportModal({visible, onClose, user}) {
  const [userId, setUserId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState('');
  const [kind, setKind] = useState('support');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const scrollRef = useRef(null);
  const pollRef = useRef(null);

  const refresh = useCallback(async uid => {
    const id = uid || userId;
    if (!id) return;
    const th = await fetchMyFeedback(id);
    setMessages(Array.isArray(th.messages) ? th.messages : []);
    setLoading(false);
  }, [userId]);

  // בכל פתיחה: בונה/טוען את המזהה, מושך הודעות, ומתחיל poll כל 15 שניות
  useEffect(() => {
    if (!visible) {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    let alive = true;
    setLoading(true);
    (async () => {
      const id = await resolveUserId(user);
      if (!alive) return;
      setUserId(id);
      await refresh(id);
      pollRef.current = setInterval(() => refresh(id), 15000);
    })();
    return () => { alive = false; if (pollRef.current) clearInterval(pollRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  useEffect(() => {
    if (scrollRef.current) setTimeout(() => scrollRef.current.scrollToEnd({animated: true}), 100);
  }, [messages]);

  const send = useCallback(async () => {
    const t = text.trim();
    if (!t || sending || !userId) return;
    setSending(true);
    // הוספה אופטימית מיידית
    setMessages(m => [...m, {from: 'user', text: t, kind, ts: new Date().toISOString()}]);
    setText('');
    const ok = await sendFeedback({
      userId, name: user?.name, email: user?.email, text: t, kind,
    });
    setSending(false);
    if (ok) refresh(userId);
  }, [text, sending, userId, kind, user, refresh]);

  const kindLabel = k => (KINDS.find(x => x.k === k) || {}).label || '';

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.overlay}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.sheet}>
          <View style={styles.header}>
            <TouchableOpacity onPress={onClose} hitSlop={{top: 10, bottom: 10, left: 10, right: 10}}>
              <Text style={styles.close}>✕</Text>
            </TouchableOpacity>
            <Text style={styles.title}>תמיכה וצ'אט עם המנהלים</Text>
            <View style={{width: 22}} />
          </View>

          {/* בחירת סוג ההודעה */}
          <View style={styles.kinds}>
            {KINDS.map(x => (
              <TouchableOpacity
                key={x.k}
                style={[styles.kindBtn, kind === x.k && styles.kindBtnOn]}
                onPress={() => setKind(x.k)}>
                <Text style={[styles.kindTxt, kind === x.k && styles.kindTxtOn]}>{x.label}</Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* היסטוריית ההודעות */}
          {loading ? (
            <View style={styles.loadingBox}><ActivityIndicator color="#e50914" /></View>
          ) : (
            <ScrollView ref={scrollRef} style={styles.chat} contentContainerStyle={{paddingVertical: 8}}>
              {messages.length === 0 ? (
                <Text style={styles.empty}>
                  {'כתבו לנו כל דבר — בעיה, חוות דעת או רעיון לשיפור.\nנקרא ונחזור אליכם כאן 💙'}
                </Text>
              ) : (
                messages.map((m, i) => {
                  const mine = m.from === 'user';
                  return (
                    <View key={i} style={[styles.bubbleRow, mine ? styles.rowRight : styles.rowLeft]}>
                      <View style={[styles.bubble, mine ? styles.bubbleMine : styles.bubbleAdmin]}>
                        {mine && m.kind ? (
                          <Text style={styles.bubbleKind}>{kindLabel(m.kind)}</Text>
                        ) : null}
                        {!mine ? <Text style={styles.adminName}>ZOVEX · צוות</Text> : null}
                        <Text style={[styles.bubbleTxt, mine && styles.bubbleTxtMine]}>{m.text}</Text>
                      </View>
                    </View>
                  );
                })
              )}
            </ScrollView>
          )}

          {/* תיבת כתיבה */}
          <View style={styles.inputRow}>
            <TextInput
              style={styles.input}
              value={text}
              onChangeText={setText}
              placeholder="כתבו הודעה..."
              placeholderTextColor="#777"
              multiline
              textAlign="right"
            />
            <TouchableOpacity
              style={[styles.sendBtn, (!text.trim() || sending) && styles.sendBtnOff]}
              onPress={send}
              disabled={!text.trim() || sending}>
              <Text style={styles.sendTxt}>{sending ? '...' : 'שלח'}</Text>
            </TouchableOpacity>
          </View>

          {/* טלגרם כאופציה נוספת */}
          <TouchableOpacity
            style={styles.tgRow}
            onPress={() => Linking.openURL('https://t.me/ZOVE8').catch(() => {})}>
            <Text style={styles.tgTxt}>או פנו אלינו בטלגרם ➤</Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end'},
  sheet: {
    backgroundColor: '#141414', borderTopLeftRadius: 20, borderTopRightRadius: 20,
    paddingHorizontal: 14, paddingTop: 12, paddingBottom: 16, maxHeight: '88%',
  },
  header: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10},
  title: {color: '#fff', fontSize: 16, fontWeight: '800'},
  close: {color: '#aaa', fontSize: 20, fontWeight: '700', width: 22, textAlign: 'center'},
  kinds: {flexDirection: 'row', gap: 8, marginBottom: 8, justifyContent: 'center'},
  kindBtn: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 16,
    backgroundColor: '#222', borderWidth: 1, borderColor: '#333',
  },
  kindBtnOn: {backgroundColor: '#e50914', borderColor: '#e50914'},
  kindTxt: {color: '#bbb', fontSize: 13, fontWeight: '600'},
  kindTxtOn: {color: '#fff'},
  loadingBox: {height: 160, justifyContent: 'center', alignItems: 'center'},
  chat: {maxHeight: 340, minHeight: 140},
  empty: {color: '#888', fontSize: 14, textAlign: 'center', paddingVertical: 30, lineHeight: 22},
  bubbleRow: {marginVertical: 4, flexDirection: 'row'},
  rowRight: {justifyContent: 'flex-end'},
  rowLeft: {justifyContent: 'flex-start'},
  bubble: {maxWidth: '82%', borderRadius: 14, paddingHorizontal: 12, paddingVertical: 8},
  bubbleMine: {backgroundColor: '#e50914', borderBottomRightRadius: 4},
  bubbleAdmin: {backgroundColor: '#262626', borderBottomLeftRadius: 4},
  bubbleKind: {color: 'rgba(255,255,255,0.75)', fontSize: 11, marginBottom: 2, textAlign: 'right'},
  adminName: {color: '#e50914', fontSize: 11, fontWeight: '700', marginBottom: 2},
  bubbleTxt: {color: '#eee', fontSize: 14, textAlign: 'right', lineHeight: 20},
  bubbleTxtMine: {color: '#fff'},
  inputRow: {flexDirection: 'row', alignItems: 'flex-end', gap: 8, marginTop: 8},
  input: {
    flex: 1, backgroundColor: '#1e1e1e', borderRadius: 14, color: '#fff',
    paddingHorizontal: 14, paddingVertical: 10, maxHeight: 100, fontSize: 14,
    borderWidth: 1, borderColor: '#2a2a2a',
  },
  sendBtn: {backgroundColor: '#e50914', borderRadius: 14, paddingHorizontal: 18, paddingVertical: 12},
  sendBtnOff: {backgroundColor: '#3a1416'},
  sendTxt: {color: '#fff', fontWeight: '800', fontSize: 14},
  tgRow: {alignItems: 'center', paddingTop: 12},
  tgTxt: {color: '#5b9bd5', fontSize: 13, fontWeight: '600'},
});
