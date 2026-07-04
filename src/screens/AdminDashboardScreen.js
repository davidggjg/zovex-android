import React, {useState, useEffect, useCallback} from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  FlatList,
  Modal,
  ScrollView,
  Alert,
  ActivityIndicator,
  Image,
  KeyboardAvoidingView,
  Platform,
  Switch,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

const REPO = 'davidggjg/zovex-android';
const FILE_PATH = 'public/movies.json';
const WEBSITE_MOVIES_URL =
  'https://raw.githubusercontent.com/davidggjg/zovex/main/public/movies.json';
const TOKEN_KEY = 'zovex_admin_gh_token';

function genId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

const EMPTY_MOVIE = {
  id: '',
  title: '',
  description: '',
  thumbnail_url: '',
  category: '',
  type: 'youtube',
  video_id: '',
  video_url: '',
  series_name: '',
  season_number: '',
  episode_number: '',
  episode_title: '',
  is_series: false,
  is_live: false,
  created_date: new Date().toISOString().slice(0, 10),
};

const VIDEO_TYPES = ['youtube', 'direct', 'kaltura', 'dailymotion', 'drive'];

// ── GitHub API helpers ────────────────────────────────────────────────────────

async function ghGetFile(token) {
  const res = await fetch(
    `https://api.github.com/repos/${REPO}/contents/${FILE_PATH}`,
    {headers: {Authorization: `token ${token}`, Accept: 'application/vnd.github.v3+json'}},
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || `HTTP ${res.status}`);
  }
  return res.json();
}

function b64Encode(str) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let result = '';
  const bytes = [];
  for (let i = 0; i < str.length; i++) {
    const c = str.charCodeAt(i);
    if (c < 128) bytes.push(c);
    else if (c < 2048) { bytes.push((c >> 6) | 192); bytes.push((c & 63) | 128); }
    else { bytes.push((c >> 12) | 224); bytes.push(((c >> 6) & 63) | 128); bytes.push((c & 63) | 128); }
  }
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i], b1 = bytes[i + 1] || 0, b2 = bytes[i + 2] || 0;
    result += chars[b0 >> 2];
    result += chars[((b0 & 3) << 4) | (b1 >> 4)];
    result += i + 1 < bytes.length ? chars[((b1 & 15) << 2) | (b2 >> 6)] : '=';
    result += i + 2 < bytes.length ? chars[b2 & 63] : '=';
  }
  return result;
}

function b64Decode(str) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const clean = str.replace(/[\r\n]/g, '').replace(/=/g, '');
  let result = '';
  for (let i = 0; i < clean.length; i += 4) {
    const c0 = chars.indexOf(clean[i]), c1 = chars.indexOf(clean[i + 1]);
    const c2 = chars.indexOf(clean[i + 2]), c3 = chars.indexOf(clean[i + 3]);
    result += String.fromCharCode((c0 << 2) | (c1 >> 4));
    if (c2 !== -1) result += String.fromCharCode(((c1 & 15) << 4) | (c2 >> 2));
    if (c3 !== -1) result += String.fromCharCode(((c2 & 3) << 6) | c3);
  }
  return result;
}

async function ghSaveFile(token, movies, sha) {
  const content = b64Encode(JSON.stringify(movies, null, 2));
  const body = {
    message: `ניהול: עדכון רשימת סרטים`,
    content,
    ...(sha ? {sha} : {}),
  };
  const res = await fetch(
    `https://api.github.com/repos/${REPO}/contents/${FILE_PATH}`,
    {
      method: 'PUT',
      headers: {
        Authorization: `token ${token}`,
        Accept: 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.message || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── MovieForm modal ───────────────────────────────────────────────────────────

function MovieForm({movie, onSave, onClose}) {
  const [form, setForm] = useState(() => ({
    ...EMPTY_MOVIE,
    ...movie,
    is_series: !!(movie?.series_name),
    season_number: movie?.season_number ? String(movie.season_number) : '',
    episode_number: movie?.episode_number ? String(movie.episode_number) : '',
  }));

  const set = (k, v) => setForm(f => ({...f, [k]: v}));

  const handleSave = () => {
    if (!form.title.trim()) { Alert.alert('שגיאה', 'כותרת חובה'); return; }
    if (!form.category.trim()) { Alert.alert('שגיאה', 'קטגוריה חובה'); return; }
    if (!form.video_id.trim() && !form.video_url.trim()) {
      Alert.alert('שגיאה', 'Video ID או URL חובה');
      return;
    }
    const m = {
      ...form,
      id: form.id || genId(),
      season_number: form.season_number ? parseInt(form.season_number, 10) : undefined,
      episode_number: form.episode_number ? parseInt(form.episode_number, 10) : undefined,
      series_name: form.is_series ? form.series_name : undefined,
      episode_title: form.is_series ? form.episode_title : undefined,
      created_date: form.created_date || new Date().toISOString().slice(0, 10),
    };
    if (!m.series_name) delete m.series_name;
    if (!m.episode_title) delete m.episode_title;
    if (!m.season_number) delete m.season_number;
    if (!m.episode_number) delete m.episode_number;
    delete m.is_series;
    onSave(m);
  };

  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={{flex: 1, backgroundColor: '#0a0a0a'}}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={fStyles.header}>
          <TouchableOpacity onPress={onClose}>
            <Text style={fStyles.closeTxt}>✕</Text>
          </TouchableOpacity>
          <Text style={fStyles.headerTitle}>
            {form.id ? 'עריכת סרטון' : 'הוספת סרטון'}
          </Text>
          <TouchableOpacity onPress={handleSave}>
            <Text style={fStyles.saveTxt}>שמור</Text>
          </TouchableOpacity>
        </View>
        <ScrollView style={{flex: 1}} contentContainerStyle={fStyles.body} keyboardShouldPersistTaps="handled">
          <Field label="כותרת *" value={form.title} onChange={v => set('title', v)} />
          <Field label="קטגוריה *" value={form.category} onChange={v => set('category', v)} placeholder="לדוגמה: סרטים, סדרות" />
          <Field label="תיאור" value={form.description} onChange={v => set('description', v)} multiline />
          <Field label="Thumbnail URL" value={form.thumbnail_url} onChange={v => set('thumbnail_url', v)} keyboardType="url" />

          <Text style={fStyles.label}>סוג וידאו *</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{marginBottom: 12}}>
            {VIDEO_TYPES.map(t => (
              <TouchableOpacity
                key={t}
                onPress={() => set('type', t)}
                style={[fStyles.typeBtn, form.type === t && fStyles.typeBtnActive]}>
                <Text style={[fStyles.typeText, form.type === t && fStyles.typeTextActive]}>
                  {t}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          <Field
            label={form.type === 'direct' ? 'URL ישיר' : 'Video ID'}
            value={form.type === 'direct' ? form.video_url : form.video_id}
            onChange={v => form.type === 'direct' ? set('video_url', v) : set('video_id', v)}
            keyboardType="url"
          />

          <View style={fStyles.toggleRow}>
            <Text style={fStyles.label}>זה שידור חי?</Text>
            <Switch
              value={form.is_live}
              onValueChange={v => set('is_live', v)}
              trackColor={{true: '#e50914'}}
            />
          </View>

          <View style={fStyles.toggleRow}>
            <Text style={fStyles.label}>חלק מסדרה?</Text>
            <Switch
              value={form.is_series}
              onValueChange={v => set('is_series', v)}
              trackColor={{true: '#e50914'}}
            />
          </View>

          {form.is_series && (
            <>
              <Field label="שם הסדרה" value={form.series_name} onChange={v => set('series_name', v)} />
              <Field label="עונה" value={form.season_number} onChange={v => set('season_number', v)} keyboardType="number-pad" />
              <Field label="פרק" value={form.episode_number} onChange={v => set('episode_number', v)} keyboardType="number-pad" />
              <Field label="שם הפרק" value={form.episode_title} onChange={v => set('episode_title', v)} />
            </>
          )}

          <Field label="תאריך הוספה (YYYY-MM-DD)" value={form.created_date} onChange={v => set('created_date', v)} />

          <TouchableOpacity style={fStyles.saveBtn} onPress={handleSave}>
            <Text style={fStyles.saveBtnText}>
              {form.id ? '✏️ עדכן סרטון' : '➕ הוסף סרטון'}
            </Text>
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function Field({label, value, onChange, multiline, keyboardType, placeholder}) {
  return (
    <>
      <Text style={fStyles.label}>{label}</Text>
      <TextInput
        style={[fStyles.input, multiline && fStyles.multiline]}
        value={value}
        onChangeText={onChange}
        multiline={multiline}
        numberOfLines={multiline ? 3 : 1}
        keyboardType={keyboardType}
        placeholder={placeholder}
        placeholderTextColor="#444"
        textAlign="right"
        textAlignVertical={multiline ? 'top' : 'center'}
        color="#fff"
      />
    </>
  );
}

const fStyles = StyleSheet.create({
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
  closeTxt: {color: '#aaa', fontSize: 20, padding: 4},
  saveTxt: {color: '#e50914', fontSize: 15, fontWeight: '700', padding: 4},
  body: {padding: 16, paddingBottom: 40},
  label: {color: '#aaa', fontSize: 12, fontWeight: '700', marginBottom: 6, marginTop: 14, textAlign: 'right'},
  input: {
    backgroundColor: '#1a1a1a',
    borderWidth: 1.5,
    borderColor: '#2a2a2a',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: '#fff',
    fontSize: 14,
  },
  multiline: {minHeight: 72, textAlignVertical: 'top'},
  typeBtn: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    marginRight: 8,
    borderRadius: 20,
    backgroundColor: '#1a1a1a',
    borderWidth: 1,
    borderColor: '#333',
  },
  typeBtnActive: {backgroundColor: '#e50914', borderColor: '#e50914'},
  typeText: {color: '#aaa', fontSize: 13},
  typeTextActive: {color: '#fff', fontWeight: '700'},
  toggleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 14,
  },
  saveBtn: {
    backgroundColor: '#e50914',
    borderRadius: 14,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 28,
  },
  saveBtnText: {color: '#fff', fontSize: 16, fontWeight: '700'},
});

// ── Main Dashboard ────────────────────────────────────────────────────────────

export default function AdminDashboardScreen({navigation}) {
  const [token, setToken] = useState('');
  const [movies, setMovies] = useState([]);
  const [fileSha, setFileSha] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editMovie, setEditMovie] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [showTokenInput, setShowTokenInput] = useState(false);
  const [tokenDraft, setTokenDraft] = useState('');
  const [search, setSearch] = useState('');

  useEffect(() => {
    AsyncStorage.getItem(TOKEN_KEY).then(t => {
      if (t) { setToken(t); loadMovies(t); }
      else setShowTokenInput(true);
    }).catch(() => {});
  }, []);

  const loadMovies = useCallback(async (tok) => {
    const t = tok || token;
    if (!t) { setShowTokenInput(true); return; }
    setLoading(true);
    try {
      const file = await ghGetFile(t);
      setFileSha(file.sha);
      const decoded = b64Decode(file.content);
      const data = JSON.parse(decoded);
      setMovies(Array.isArray(data) ? data : []);
    } catch (err) {
      // File might not exist yet or be empty, try website fallback
      try {
        const res = await fetch(WEBSITE_MOVIES_URL + '?t=' + Date.now());
        const data = await res.json();
        setMovies(Array.isArray(data) ? data : []);
        setFileSha('');
      } catch {
        Alert.alert('שגיאה', 'לא ניתן לטעון: ' + err.message);
        setMovies([]);
      }
    } finally {
      setLoading(false);
    }
  }, [token]);

  const saveToken = async () => {
    const t = tokenDraft.trim();
    if (!t) return;
    setToken(t);
    setShowTokenInput(false);
    await AsyncStorage.setItem(TOKEN_KEY, t).catch(() => {});
    loadMovies(t);
  };

  const commitMovies = async (newMovies) => {
    if (!token) { Alert.alert('שגיאה', 'אין טוקן'); return; }
    setSaving(true);
    try {
      const result = await ghSaveFile(token, newMovies, fileSha);
      setFileSha(result.content.sha);
      setMovies(newMovies);
      Alert.alert('הצלחה', 'הסרטים עודכנו!');
    } catch (err) {
      Alert.alert('שגיאת שמירה', err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleSaveMovie = (movie) => {
    const idx = movies.findIndex(m => m.id === movie.id);
    const updated = idx >= 0
      ? movies.map((m, i) => (i === idx ? movie : m))
      : [...movies, movie];
    setShowForm(false);
    setEditMovie(null);
    commitMovies(updated);
  };

  const handleDelete = (id) => {
    Alert.alert('מחק סרטון', 'בטוח שרוצה למחוק?', [
      {text: 'ביטול', style: 'cancel'},
      {
        text: 'מחק',
        style: 'destructive',
        onPress: () => commitMovies(movies.filter(m => m.id !== id)),
      },
    ]);
  };

  const filtered = search
    ? movies.filter(m =>
        (m.title || '').toLowerCase().includes(search.toLowerCase()) ||
        (m.series_name || '').toLowerCase().includes(search.toLowerCase()),
      )
    : movies;

  if (showTokenInput) {
    return (
      <View style={styles.container}>
        <TouchableOpacity style={styles.backBtn} onPress={() => navigation.goBack()}>
          <Text style={styles.backTxt}>✕</Text>
        </TouchableOpacity>
        <View style={styles.tokenCard}>
          <Text style={styles.tokenTitle}>GitHub Token</Text>
          <Text style={styles.tokenSub}>נדרש PAT עם הרשאות repo לעדכון סרטים</Text>
          <TextInput
            style={styles.tokenInput}
            placeholder="ghp_..."
            placeholderTextColor="#555"
            secureTextEntry
            value={tokenDraft}
            onChangeText={setTokenDraft}
            textAlign="right"
          />
          <TouchableOpacity style={styles.btn} onPress={saveToken}>
            <Text style={styles.btnText}>שמור טוקן</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn2}>
          <Text style={styles.backTxt}>✕</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>ניהול סרטים ({movies.length})</Text>
        <TouchableOpacity onPress={() => setShowTokenInput(true)}>
          <Text style={styles.tokenBtn}>טוקן</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.searchRow}>
        <TextInput
          style={styles.searchInput}
          placeholder="חיפוש..."
          placeholderTextColor="#555"
          value={search}
          onChangeText={setSearch}
          textAlign="right"
        />
        <TouchableOpacity
          style={styles.addBtn}
          onPress={() => {setEditMovie(null); setShowForm(true);}}>
          <Text style={styles.addBtnText}>+ הוסף</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.refreshBtn}
          onPress={() => loadMovies()}>
          <Text style={styles.refreshTxt}>↻</Text>
        </TouchableOpacity>
      </View>

      {(loading || saving) && (
        <View style={styles.loadingBar}>
          <ActivityIndicator color="#e50914" size="small" />
          <Text style={styles.loadingTxt}>{saving ? 'שומר...' : 'טוען...'}</Text>
        </View>
      )}

      <FlatList
        data={filtered}
        keyExtractor={item => String(item.id)}
        contentContainerStyle={styles.list}
        renderItem={({item}) => (
          <View style={styles.movieRow}>
            {item.thumbnail_url ? (
              <Image source={{uri: item.thumbnail_url}} style={styles.thumb} />
            ) : (
              <View style={[styles.thumb, styles.thumbEmpty]}>
                <Text style={{fontSize: 18}}>{item.is_live ? '📡' : '🎬'}</Text>
              </View>
            )}
            <View style={styles.movieInfo}>
              <Text style={styles.movieTitle} numberOfLines={2}>
                {item.title}
              </Text>
              <Text style={styles.movieMeta} numberOfLines={1}>
                {[item.category, item.type, item.series_name].filter(Boolean).join(' · ')}
              </Text>
            </View>
            <View style={styles.movieActions}>
              <TouchableOpacity
                onPress={() => {setEditMovie(item); setShowForm(true);}}
                style={styles.editBtn}>
                <Text style={styles.editBtnTxt}>✏️</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => handleDelete(item.id)}
                style={styles.deleteBtn}>
                <Text style={styles.deleteBtnTxt}>🗑</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}
        ListEmptyComponent={
          !loading && (
            <View style={styles.empty}>
              <Text style={styles.emptyText}>אין סרטים עדיין</Text>
              <Text style={styles.emptySub}>לחץ "+ הוסף" להוספת הסרטון הראשון</Text>
            </View>
          )
        }
      />

      {showForm && (
        <MovieForm
          movie={editMovie}
          onSave={handleSaveMovie}
          onClose={() => {setShowForm(false); setEditMovie(null);}}
        />
      )}
    </View>
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
  headerTitle: {color: '#fff', fontSize: 15, fontWeight: '700'},
  backBtn: {
    position: 'absolute',
    top: 20,
    right: 20,
    zIndex: 10,
    padding: 8,
  },
  backBtn2: {padding: 4},
  backTxt: {color: '#aaa', fontSize: 20},
  tokenBtn: {color: '#e50914', fontSize: 13, fontWeight: '600', padding: 4},
  tokenCard: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 28,
    alignItems: 'center',
  },
  tokenTitle: {color: '#fff', fontSize: 20, fontWeight: '800', marginBottom: 6},
  tokenSub: {color: '#666', fontSize: 13, textAlign: 'center', marginBottom: 24, lineHeight: 20},
  tokenInput: {
    width: '100%',
    backgroundColor: '#1a1a1a',
    borderWidth: 1.5,
    borderColor: '#333',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: '#fff',
    fontSize: 14,
    marginBottom: 16,
  },
  btn: {
    width: '100%',
    backgroundColor: '#e50914',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  btnText: {color: '#fff', fontSize: 15, fontWeight: '700'},
  searchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    gap: 8,
  },
  searchInput: {
    flex: 1,
    backgroundColor: '#1a1a1a',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 9,
    color: '#fff',
    fontSize: 13,
    borderWidth: 1,
    borderColor: '#2a2a2a',
  },
  addBtn: {
    backgroundColor: '#e50914',
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  addBtnText: {color: '#fff', fontSize: 13, fontWeight: '700'},
  refreshBtn: {
    backgroundColor: '#1a1a1a',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderWidth: 1,
    borderColor: '#2a2a2a',
  },
  refreshTxt: {color: '#aaa', fontSize: 16},
  loadingBar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
    gap: 8,
    backgroundColor: '#111',
  },
  loadingTxt: {color: '#aaa', fontSize: 13},
  list: {paddingHorizontal: 12, paddingBottom: 20},
  movieRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#1a1a1a',
  },
  thumb: {width: 72, height: 48, borderRadius: 6, resizeMode: 'cover'},
  thumbEmpty: {
    backgroundColor: '#1c1c1e',
    justifyContent: 'center',
    alignItems: 'center',
  },
  movieInfo: {flex: 1, marginHorizontal: 10},
  movieTitle: {color: '#f2f2f2', fontSize: 13, fontWeight: '600', textAlign: 'right'},
  movieMeta: {color: '#666', fontSize: 11, marginTop: 3, textAlign: 'right'},
  movieActions: {flexDirection: 'row', gap: 6},
  editBtn: {
    backgroundColor: '#1a1a1a',
    borderRadius: 8,
    padding: 8,
    borderWidth: 1,
    borderColor: '#333',
  },
  editBtnTxt: {fontSize: 14},
  deleteBtn: {
    backgroundColor: '#2a1010',
    borderRadius: 8,
    padding: 8,
    borderWidth: 1,
    borderColor: '#4a1010',
  },
  deleteBtnTxt: {fontSize: 14},
  empty: {alignItems: 'center', marginTop: 80, paddingHorizontal: 30},
  emptyText: {color: '#aaa', fontSize: 18, fontWeight: '600', marginBottom: 8},
  emptySub: {color: '#555', fontSize: 13, textAlign: 'center'},
});
