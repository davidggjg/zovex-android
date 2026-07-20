import React, {useEffect, useState, useMemo, useCallback, useRef, memo} from 'react';
import {
  View,
  Text,
  Alert,
  Modal,
  Linking,
  FlatList,
  TextInput,
  TouchableOpacity,
  Image,
  StyleSheet,
  ActivityIndicator,
  ScrollView,
  RefreshControl,
  Dimensions,
  ImageBackground,
  Animated,
  I18nManager,
  AppState,
} from 'react-native';
import {GoogleSignin} from '@react-native-google-signin/google-signin';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  fetchMovies,
  fetchHistory,
  clearCache,
} from '../api/movies';
import {getUserId} from '../api/userStore';
import {
  getDownloads,
  downloadItem,
  deleteDownload,
  preparePlayback,
  downloadEntryToMovie,
  isItemDownloadable,
} from '../api/downloads';

const DOWNLOADS_CATEGORY = 'ההורדות שלי';

const {width: SW} = Dimensions.get('window');
// 3 cards + 5px margin each side + 8px grid padding each side = 3*CARD_W + 30 + 16 = SW
const CARD_W = Math.floor((SW - 46) / 3);
const CARD_H = Math.floor(CARD_W * 1.48);
// Hero banner: tall enough to show portrait thumbnails (2:3) with contain mode
const HERO_H = Math.round(SW * 1.25);

const ADMIN_TRIGGER = 'ZovexAdmin2026';
const USER_KEY = 'zovex_google_user';
const SEEN_LOGIN_KEY = 'zovex_seen_login';
const TG_TIP_KEY = 'zovex_hide_telegram_tip';

GoogleSignin.configure({
  scopes: ['profile', 'email'],
  offlineAccess: false,
});

// ── Movie Detail Modal ────────────────────────────────────────────────────────

function DownloadControl({item, compact, downloadedIds, downloadingId, downloadProgress, onDownload, onDeleteDownload}) {
  if (!item || !isItemDownloadable(item)) return null;
  const id = String(item.id);
  const isThisDownloading = downloadingId === id;
  const isDownloaded = downloadedIds.has(id);

  if (isThisDownloading) {
    const pct = Math.round((downloadProgress?.pct || 0) * 100);
    const label = downloadProgress?.phase === 'encrypting' ? 'מצפין' : 'מוריד';
    // Files here are often 1GB+ over a slow connection, so the percentage
    // alone can sit unchanged for a long time and look frozen. Showing the
    // live MB count too gives visible movement within a second or two.
    const mb = downloadProgress?.contentLength
      ? `${Math.round((downloadProgress.bytesWritten || 0) / 1048576)}/${Math.round(downloadProgress.contentLength / 1048576)}MB`
      : null;
    return (
      <View style={[mdStyles.dlBtn, compact && mdStyles.dlBtnCompact]}>
        <ActivityIndicator size="small" color="#e50914" />
        {!compact && (
          <Text style={mdStyles.dlBtnTxt}>{label} {pct}%{mb ? ` · ${mb}` : ''}</Text>
        )}
      </View>
    );
  }
  if (isDownloaded) {
    return (
      <TouchableOpacity
        style={[mdStyles.dlBtn, mdStyles.dlBtnDone, compact && mdStyles.dlBtnCompact]}
        activeOpacity={0.8}
        onPress={() => onDeleteDownload(id)}>
        <Text style={[mdStyles.dlBtnTxt, mdStyles.dlBtnDoneTxt]}>{compact ? '✓' : '✓ הורד · הסר'}</Text>
      </TouchableOpacity>
    );
  }
  return (
    <TouchableOpacity
      style={[mdStyles.dlBtn, compact && mdStyles.dlBtnCompact]}
      activeOpacity={0.8}
      onPress={() => onDownload(item)}>
      <Text style={mdStyles.dlBtnTxt}>{compact ? '⬇' : '⬇ הורדה'}</Text>
    </TouchableOpacity>
  );
}

function MovieDetailModal({
  item, allMovies, onClose, onPlayDirect,
  downloadedIds, downloadingId, downloadProgress, onDownload, onDeleteDownload,
}) {
  const [selectedSeason, setSelectedSeason] = useState(null);
  const [showSeasonPicker, setShowSeasonPicker] = useState(false);
  const [seasonLoading, setSeasonLoading] = useState(false);

  const episodes = useMemo(() => {
    if (!item?.series_name) return [];
    return allMovies
      .filter(m => m.series_name === item.series_name)
      .sort((a, b) => {
        const sa = a.season_number || 1, sb = b.season_number || 1;
        if (sa !== sb) return sa - sb;
        return (a.episode_number || 0) - (b.episode_number || 0);
      });
  }, [item, allMovies]);

  const seasons = useMemo(
    () => [...new Set(episodes.map(e => e.season_number).filter(Boolean))].sort((a, b) => a - b),
    [episodes],
  );
  const activeSeason = selectedSeason ?? (seasons.length > 0 ? seasons[0] : null);

  const visibleEpisodes = useMemo(
    () => (activeSeason ? episodes.filter(e => e.season_number === activeSeason) : episodes),
    [episodes, activeSeason],
  );

  const handleSeasonSelect = useCallback((s) => {
    setShowSeasonPicker(false);
    if (s === activeSeason) return;
    setSeasonLoading(true);
    setTimeout(() => { setSelectedSeason(s); setSeasonLoading(false); }, 600);
  }, [activeSeason]);

  if (!item) return null;
  const displayTitle = item.series_name || item.title || item.name || '';
  const firstEp = visibleEpisodes.length > 0 ? visibleEpisodes[0] : null;

  return (
    <View style={mdStyles.overlay}>
      <TouchableOpacity style={StyleSheet.absoluteFillObject} onPress={onClose} activeOpacity={1} />
      <View style={mdStyles.sheet}>
        <TouchableOpacity style={mdStyles.closeBtn} onPress={onClose}>
          <Text style={mdStyles.closeTxt}>✕</Text>
        </TouchableOpacity>
        <ScrollView showsVerticalScrollIndicator={false} bounces={false}>
          {item.thumbnail_url ? (
            <Image source={{uri: item.thumbnail_url}} style={mdStyles.thumb} />
          ) : (
            <View style={mdStyles.noThumb}>
              <Text style={{fontSize: 52}}>{item.is_live ? '📡' : '🎬'}</Text>
            </View>
          )}
          <View style={mdStyles.body}>
            <Text style={mdStyles.title}>{displayTitle}</Text>
            {!!item.description && (
              <Text style={mdStyles.desc} numberOfLines={5}>{item.description}</Text>
            )}
            <View style={mdStyles.actionsRow}>
              <TouchableOpacity style={mdStyles.playBtn} activeOpacity={0.8} onPress={() => onPlayDirect(firstEp || item)}>
                <Text style={mdStyles.playTxt}>▶ הפעל</Text>
              </TouchableOpacity>
              <DownloadControl
                item={firstEp || item}
                downloadedIds={downloadedIds}
                downloadingId={downloadingId}
                downloadProgress={downloadProgress}
                onDownload={onDownload}
                onDeleteDownload={onDeleteDownload}
              />
            </View>
          </View>
          {episodes.length > 1 && (
            <View style={mdStyles.epsSection}>
              {seasons.length > 1 && (
                <View style={mdStyles.seasonRow}>
                  <TouchableOpacity style={mdStyles.seasonBtn} onPress={() => setShowSeasonPicker(true)} activeOpacity={0.8}>
                    <Text style={mdStyles.seasonBtnTxt}>עונה {activeSeason} ▾</Text>
                  </TouchableOpacity>
                </View>
              )}
              <Text style={mdStyles.epsHeader}>פרקים ({visibleEpisodes.length})</Text>
              {seasonLoading ? (
                <View style={{alignItems: 'center', paddingVertical: 30}}>
                  <ActivityIndicator size="large" color="#e50914" />
                </View>
              ) : (
                visibleEpisodes.map(ep => (
                  <TouchableOpacity key={ep.id} style={mdStyles.epRow} activeOpacity={0.75} onPress={() => onPlayDirect(ep)}>
                    {ep.thumbnail_url ? (
                      <Image source={{uri: ep.thumbnail_url}} style={mdStyles.epThumb} />
                    ) : (
                      <View style={mdStyles.epThumbEmpty}>
                        <Text style={{fontSize: 16, color: '#aaa'}}>▶</Text>
                      </View>
                    )}
                    <View style={mdStyles.epInfo}>
                      <Text style={mdStyles.epNum}>
                        {ep.season_number ? `עונה ${ep.season_number} · ` : ''}פרק {ep.episode_number}
                      </Text>
                      <Text style={mdStyles.epTitle} numberOfLines={2}>
                        {ep.episode_title || ep.title}
                      </Text>
                    </View>
                    <DownloadControl
                      item={ep}
                      compact
                      downloadedIds={downloadedIds}
                      downloadingId={downloadingId}
                      downloadProgress={downloadProgress}
                      onDownload={onDownload}
                      onDeleteDownload={onDeleteDownload}
                    />
                    <Text style={mdStyles.epPlayIcon}>▶</Text>
                  </TouchableOpacity>
                ))
              )}
            </View>
          )}
        </ScrollView>
      </View>

      {showSeasonPicker && (
        <Modal transparent animationType="fade" visible={showSeasonPicker} onRequestClose={() => setShowSeasonPicker(false)}>
          <TouchableOpacity style={mdStyles.seasonPickerOverlay} activeOpacity={1} onPress={() => setShowSeasonPicker(false)}>
            <View style={mdStyles.seasonPickerBox} onStartShouldSetResponder={() => true}>
              {seasons.map(s => (
                <TouchableOpacity key={s} style={[mdStyles.seasonPickerItem, s === activeSeason && mdStyles.seasonPickerItemActive]} onPress={() => handleSeasonSelect(s)}>
                  <Text style={[mdStyles.seasonPickerTxt, s === activeSeason && mdStyles.seasonPickerTxtActive]}>עונה {s}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </TouchableOpacity>
        </Modal>
      )}
    </View>
  );
}

const mdStyles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: '#0a0a0a',
    zIndex: 100,
  },
  sheet: {flex: 1, overflow: 'hidden', backgroundColor: '#0a0a0a'},
  closeBtn: {
    position: 'absolute', top: 14, right: 14, zIndex: 10,
    backgroundColor: 'rgba(0,0,0,0.65)', borderRadius: 20,
    width: 38, height: 38, justifyContent: 'center', alignItems: 'center',
  },
  closeTxt: {color: '#fff', fontSize: 14, fontWeight: '700'},
  thumb: {width: '100%', height: 260, resizeMode: 'cover'},
  noThumb: {width: '100%', height: 200, backgroundColor: '#1c1c1e', justifyContent: 'center', alignItems: 'center'},
  body: {padding: 18},
  title: {color: '#fff', fontSize: 20, fontWeight: '800', textAlign: 'right', marginBottom: 8},
  desc: {color: '#aaa', fontSize: 13, lineHeight: 20, textAlign: 'right', marginBottom: 16},
  actionsRow: {flexDirection: 'row', gap: 10},
  playBtn: {flex: 1, backgroundColor: '#e50914', borderRadius: 12, paddingVertical: 14, alignItems: 'center'},
  playTxt: {color: '#fff', fontSize: 16, fontWeight: '800'},
  dlBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
    backgroundColor: '#2a2a2a', borderRadius: 12, paddingVertical: 14, paddingHorizontal: 16,
  },
  dlBtnCompact: {
    paddingVertical: 6, paddingHorizontal: 8, borderRadius: 16, marginHorizontal: 6, minWidth: 34,
  },
  dlBtnTxt: {color: '#e5e5e5', fontSize: 13, fontWeight: '700'},
  dlBtnDone: {backgroundColor: 'rgba(76,175,80,0.16)'},
  dlBtnDoneTxt: {color: '#4caf50'},
  epsSection: {paddingHorizontal: 16, paddingBottom: 24},
  seasonRow: {flexDirection: 'row', justifyContent: 'flex-end', paddingTop: 14, paddingBottom: 4, borderTopWidth: 1, borderTopColor: '#222'},
  seasonBtn: {backgroundColor: '#2a2a2a', borderRadius: 20, paddingHorizontal: 16, paddingVertical: 8},
  seasonBtnTxt: {color: '#fff', fontSize: 14, fontWeight: '700'},
  seasonPickerOverlay: {flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'center', alignItems: 'center'},
  seasonPickerBox: {backgroundColor: '#1c1c1e', borderRadius: 16, overflow: 'hidden', minWidth: 180},
  seasonPickerItem: {paddingVertical: 18, paddingHorizontal: 28, alignItems: 'center'},
  seasonPickerItemActive: {backgroundColor: '#2a2a2a'},
  seasonPickerTxt: {color: '#ccc', fontSize: 16, fontWeight: '600'},
  seasonPickerTxtActive: {color: '#e50914', fontSize: 17, fontWeight: '800'},
  epsHeader: {color: '#fff', fontSize: 15, fontWeight: '800', textAlign: 'right', marginBottom: 10, paddingTop: 10},
  epRow: {flexDirection: 'row', alignItems: 'center', paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#1a1a1a'},
  epThumb: {width: 110, height: 62, borderRadius: 6, resizeMode: 'cover'},
  epThumbEmpty: {width: 110, height: 62, borderRadius: 6, backgroundColor: '#222', justifyContent: 'center', alignItems: 'center'},
  epInfo: {flex: 1, marginHorizontal: 10},
  epNum: {color: '#e50914', fontSize: 11, fontWeight: '700', textAlign: 'right'},
  epTitle: {color: '#f2f2f2', fontSize: 13, fontWeight: '600', textAlign: 'right', marginTop: 3},
  epPlayIcon: {color: '#e50914', fontSize: 14},
});

// ── HeroBanner ────────────────────────────────────────────────────────────────

function HeroBanner({movies, onPlay, onInfo}) {
  const heroMovies = useMemo(() => {
    // Sort by created_date first (newest first) - movies.json isn't
    // guaranteed to be in any particular order (different tools that write
    // to it append vs. prepend differently), so relying on raw array
    // position here means genuinely new content can end up buried and
    // never surface in the banner at all. Missing dates sort last.
    const sorted = [...movies].sort((a, b) => {
      const da = a.created_date ? new Date(a.created_date).getTime() : 0;
      const db = b.created_date ? new Date(b.created_date).getTime() : 0;
      return db - da;
    });
    const seen = {};
    const result = sorted.filter(m => {
      if (m.series_name) { if (seen[m.series_name]) return false; seen[m.series_name] = true; }
      return true;
    }).slice(0, 6);
    return result;
  }, [movies]);

  const [index, setIndex] = useState(0);
  const fadeAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (heroMovies.length < 2) return;
    const t = setInterval(() => {
      Animated.timing(fadeAnim, {toValue: 0, duration: 400, useNativeDriver: true}).start(() => {
        setIndex(i => (i + 1) % heroMovies.length);
        Animated.timing(fadeAnim, {toValue: 1, duration: 400, useNativeDriver: true}).start();
      });
    }, 8000);
    return () => clearInterval(t);
  }, [heroMovies.length, fadeAnim]);

  if (heroMovies.length === 0) return null;
  const movie = heroMovies[index % heroMovies.length];

  return (
    <Animated.View style={[styles.hero, {opacity: fadeAnim}]}>
      {movie.thumbnail_url ? (
        <ImageBackground source={{uri: movie.thumbnail_url}} style={styles.heroBg} resizeMode="contain">
          <View style={styles.heroGradient} />
          <View style={styles.heroContent}>
            <Text style={styles.heroTitle} numberOfLines={2}>{movie.series_name || movie.title}</Text>
            {!!movie.description && <Text style={styles.heroDesc} numberOfLines={2}>{movie.description}</Text>}
            <View style={styles.heroBtns}>
              <TouchableOpacity style={styles.heroBtnPlay} activeOpacity={0.8} onPress={() => onPlay(movie)}>
                <Text style={styles.heroBtnPlayText}>▶ צפה</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.heroBtnInfo} activeOpacity={0.8} onPress={() => onInfo(movie)}>
                <Text style={styles.heroBtnInfoText}>מידע נוסף</Text>
              </TouchableOpacity>
            </View>
          </View>
        </ImageBackground>
      ) : (
        <View style={[styles.heroBg, {backgroundColor: '#111'}]}>
          <View style={styles.heroContent}>
            <Text style={styles.heroTitle}>{movie.series_name || movie.title}</Text>
            <View style={styles.heroBtns}>
              <TouchableOpacity style={styles.heroBtnPlay} activeOpacity={0.8} onPress={() => onPlay(movie)}>
                <Text style={styles.heroBtnPlayText}>▶ צפה</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      )}
      {heroMovies.length > 1 && (
        <View style={styles.heroDots}>
          {heroMovies.map((_, i) => (
            <View key={i} style={[styles.heroDot, i === index && styles.heroDotActive]} />
          ))}
        </View>
      )}
    </Animated.View>
  );
}

// ── helpers ───────────────────────────────────────────────────────────────────

function buildSeriesMap(movies) {
  const map = {};
  movies.forEach(m => {
    if (!m.series_name) return;
    if (!map[m.series_name]) {
      map[m.series_name] = {
        id: 'series_' + m.series_name,
        isSeries: true,
        series_name: m.series_name,
        name: m.series_name,
        title: m.series_name,
        thumbnail_url: m.thumbnail_url,
        description: m.description,
        category: m.category,
      };
    }
  });
  return map;
}

// ── MovieCard ─────────────────────────────────────────────────────────────────

const MovieCard = memo(function MovieCard({item, onPress}) {
  const isLive = !!item.is_live;
  return (
    <TouchableOpacity style={[styles.card, {width: CARD_W}]} onPress={() => onPress(item)} activeOpacity={0.8}>
      <View style={[styles.cardImg, {height: CARD_H, borderColor: isLive ? '#e50914' : 'transparent', borderWidth: isLive ? 2 : 0}]}>
        {item.thumbnail_url ? (
          <Image source={{uri: item.thumbnail_url}} style={styles.cardImgInner} fadeDuration={200} />
        ) : (
          <View style={styles.noThumb}><Text style={styles.thumbEmoji}>{isLive ? '📡' : '🎬'}</Text></View>
        )}
        {item.isSeries && <View style={styles.badge}><Text style={styles.badgeText}>סדרה</Text></View>}
        {isLive && <View style={[styles.badge, styles.liveBadge]}><Text style={styles.badgeText}>🔴 LIVE</Text></View>}
      </View>
      <Text style={styles.cardTitle} numberOfLines={2}>{item.name || item.title}</Text>
    </TouchableOpacity>
  );
});

// ── NetflixRow ────────────────────────────────────────────────────────────────

const NetflixRow = memo(function NetflixRow({title, items, onPress, isLiveRow}) {
  if (!items || items.length === 0) return null;
  return (
    <View style={styles.rowWrap}>
      <View style={styles.rowHeader}>
        {isLiveRow && <Text style={styles.liveIcon}>●</Text>}
        <Text style={styles.rowTitle}>{title}</Text>
      </View>
      <FlatList
        data={items}
        horizontal
        keyExtractor={item => String(item.id)}
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.rowList}
        initialNumToRender={5}
        maxToRenderPerBatch={5}
        windowSize={3}
        removeClippedSubviews
        renderItem={({item}) => <MovieCard item={item} onPress={onPress} />}
      />
    </View>
  );
});

// ── main component ────────────────────────────────────────────────────────────

export default function HomeScreen({navigation, route}) {
  const [movies, setMovies] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('הכל');
  const [detailItem, setDetailItem] = useState(null);
  const [user, setUser] = useState(null);
  const [showSignIn, setShowSignIn] = useState(false);
  const [showCatModal, setShowCatModal] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showDonation, setShowDonation] = useState(false);
  const donationCallback = useRef(null);
  const [showTgTip, setShowTgTip] = useState(false);
  const searchAnim = useRef(new Animated.Value(0)).current;
  const [downloads, setDownloads] = useState([]);
  const [downloadingId, setDownloadingId] = useState(null);
  const [downloadProgress, setDownloadProgress] = useState(null);
  const [preparingPlaybackId, setPreparingPlaybackId] = useState(null);

  const startSignIn = useCallback(async () => {
    try {
      await GoogleSignin.hasPlayServices();
      const result = await GoogleSignin.signIn();
      // v11: { type: 'success', data: { user, idToken } } | { type: 'cancelled' }
      if (!result) return;
      if (result.type === 'cancelled') return;
      // Flatten both v10 and v11 shapes
      const u = result?.data?.user ?? result?.user ?? result;
      if (!u?.email) {
        Alert.alert('Google Sign-In', `תוצאה לא צפויה:\n${JSON.stringify(result).slice(0, 200)}`);
        return;
      }
      const info = {
        id: String(u.id || u.userId || ''),
        name: u.name || u.displayName || '',
        email: u.email || '',
        given_name: u.givenName || u.familyName || '',
        picture: u.photo || u.photoUrl || '',
      };
      setUser(info);
      setShowSignIn(false);
      await AsyncStorage.setItem(USER_KEY, JSON.stringify(info)).catch(() => {});
      await AsyncStorage.setItem(SEEN_LOGIN_KEY, '1').catch(() => {});
    } catch (e) {
      const code = String(e?.code ?? '');
      // 12501 = user cancelled, -5 = cancelled — ignore silently
      if (code === '12501' || code === '-5') return;
      Alert.alert(
        'שגיאת כניסה',
        `קוד: ${code}\n${e?.message ?? String(e)}`,
      );
    }
  }, []);

  // Load saved user; auto-show sign-in for first-time users
  useEffect(() => {
    Promise.all([
      AsyncStorage.getItem(USER_KEY),
      AsyncStorage.getItem(SEEN_LOGIN_KEY),
    ]).then(([saved, seen]) => {
      if (saved) { setUser(JSON.parse(saved)); return; }
      if (!seen) setShowSignIn(true);
    }).catch(() => { setShowSignIn(true); });
  }, []);

  const signOut = useCallback(async () => {
    setUser(null);
    setHistory([]);
    await AsyncStorage.removeItem(USER_KEY).catch(() => {});
    try { await GoogleSignin.signOut(); } catch {}
  }, []);

  // Show Telegram tip unless user has dismissed it before
  useEffect(() => {
    AsyncStorage.getItem(TG_TIP_KEY).then(v => { if (!v) setShowTgTip(true); }).catch(() => {});
  }, []);

  // ── Data loading ──
  const load = useCallback(async (refresh = false, loggedInUser = null) => {
    if (refresh) { clearCache(); setRefreshing(true); }
    try {
      const [data, hist] = await Promise.all([
        fetchMovies(),
        loggedInUser ? fetchHistory(loggedInUser.id) : Promise.resolve([]),
      ]);
      setMovies(data);
      setHistory(hist);
    } catch {}
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { load(false, user); }, [load, user]);

  // The app process often stays alive in the background for a long time on
  // Android, and nothing was refetching movies.json in that case - once
  // loaded, new content (like a newly-added live channel) would never show
  // up until the user happened to pull-to-refresh or force-kill the app.
  // fetchMovies() already has its own 5-minute in-memory cache, so calling
  // load() here on every foreground return is cheap when data isn't stale
  // and just refreshes it in the background when it is.
  useEffect(() => {
    const sub = AppState.addEventListener('change', state => {
      if (state === 'active') load(false, user);
    });
    return () => sub.remove();
  }, [load, user]);

  const refreshDownloads = useCallback(() => {
    getDownloads().then(setDownloads).catch(() => {});
  }, []);
  useEffect(() => { refreshDownloads(); }, [refreshDownloads]);
  const downloadedIds = useMemo(() => new Set(downloads.map(d => d.id)), [downloads]);

  // Clear detail modal when returning from Player so no flash on back-navigate
  useEffect(() => {
    const unsub = navigation.addListener('focus', () => setDetailItem(null));
    return unsub;
  }, [navigation]);

  const seriesMap = useMemo(() => buildSeriesMap(movies), [movies]);

  const liveChannels = useMemo(() => movies.filter(m => m.is_live), [movies]);

  const allCategories = useMemo(() => {
    const cats = [...new Set(movies.filter(m => !m.is_live).map(m => m.category).filter(Boolean))];
    const tabs = ['הכל'];
    if (liveChannels.length > 0) tabs.push('שידורים חיים');
    tabs.push(...cats);
    tabs.push(DOWNLOADS_CATEGORY);
    tabs.push('היסטוריה');
    return tabs;
  }, [movies, liveChannels]);

  const q = useMemo(() => search.toLowerCase(), [search]);

  const getItemsForCategory = useCallback(cat => {
    if (cat === 'שידורים חיים') {
      return liveChannels
        .filter(ch => (ch.title || ch.name || '').toLowerCase().includes(q));
    }
    if (cat === 'היסטוריה') {
      return history.map(h => movies.find(m => m.id === h.media_id)).filter(Boolean);
    }
    if (cat === DOWNLOADS_CATEGORY) {
      return downloads.map(downloadEntryToMovie);
    }
    const seen = {};
    const result = [];
    movies.forEach(m => {
      if (m.is_live) return;
      const matchQ = (m.title||'').toLowerCase().includes(q) || (m.series_name||'').toLowerCase().includes(q);
      if (!matchQ || (cat !== 'הכל' && m.category !== cat)) return;
      if (m.series_name) {
        if (!seen[m.series_name]) { seen[m.series_name] = true; result.push({...seriesMap[m.series_name]}); }
      } else {
        result.push({...m, isSeries: false});
      }
    });
    return result;
  }, [movies, liveChannels, history, seriesMap, q, downloads]);

  const netflixRows = useMemo(() => {
    const rows = [];
    if (liveChannels.length > 0)
      rows.push({title: 'שידורים חיים', isLiveRow: true, items: liveChannels});
    const histItems = history.map(h => movies.find(m => m.id === h.media_id)).filter(Boolean);
    if (histItems.length > 0) rows.push({title: '▶ המשך צפייה', items: histItems});
    allCategories
      .filter(c => c !== 'הכל' && c !== 'שידורים חיים' && c !== 'היסטוריה' && c !== DOWNLOADS_CATEGORY)
      .forEach(cat => {
        const items = getItemsForCategory(cat);
        if (items.length > 0) rows.push({title: cat, items});
      });
    return rows;
  }, [liveChannels, history, movies, allCategories, getItemsForCategory]);

  const showDonationModal = useCallback(cb => {
    donationCallback.current = cb;
    setShowDonation(true);
  }, []);

  const handleDonationContinue = useCallback(() => {
    setShowDonation(false);
    const cb = donationCallback.current;
    donationCallback.current = null;
    cb?.();
  }, []);

  // Downloaded items are a flat "what you have offline" list (unlike the
  // online catalog's detail modal, they don't need a series/episode picker -
  // that would let you tap into episodes that were never actually
  // downloaded). Decrypt straight to a temp file and play immediately.
  const playDownloadedItem = useCallback(async item => {
    const id = item.__downloadId;
    setPreparingPlaybackId(id);
    try {
      const {uri, cleanup} = await preparePlayback(id);
      navigation.navigate('Player', {
        movie: {...item, video_url: uri, video_id: uri, type: 'direct'},
        startTime: 0,
        userId: user?.id || null,
        onLeaveCleanup: cleanup,
      });
    } catch (e) {
      Alert.alert('שגיאה', e?.message || 'לא ניתן להפעיל את ההורדה');
    } finally {
      setPreparingPlaybackId(null);
    }
  }, [navigation, user]);

  const handleDownloadItem = useCallback(async item => {
    if (downloadingId) {
      Alert.alert('הורדה', 'הורדה אחרת כבר מתבצעת - המתן שתסתיים ונסה שוב.');
      return;
    }
    const id = String(item.id);
    setDownloadingId(id);
    setDownloadProgress({phase: 'downloading', pct: 0});
    try {
      await downloadItem(item, p => setDownloadProgress(p));
      refreshDownloads();
    } catch (e) {
      Alert.alert('שגיאת הורדה', e?.message || 'לא ניתן להוריד את התוכן הזה');
    } finally {
      setDownloadingId(null);
      setDownloadProgress(null);
    }
  }, [downloadingId, refreshDownloads]);

  const handleDeleteDownload = useCallback(async id => {
    await deleteDownload(id);
    refreshDownloads();
  }, [refreshDownloads]);

  const handleItemPress = useCallback(item => {
    if (item.__isDownload) { playDownloadedItem(item); return; }
    showDonationModal(() => {
      if (item.is_live) {
        navigation.navigate('Player', {
          movie: {
            ...item,
            is_live: true,
            type: item.type || 'direct',
            video_url: item.video_url || item.url || '',
            title: item.title || item.name || 'שידור חי',
          },
          userId: user?.id || null,
        });
      } else {
        setDetailItem(item);
      }
    });
  }, [navigation, user, showDonationModal, playDownloadedItem]);

  // Deep link support: zovex://<slug> or https://davidggjg.github.io/zovex/<slug>
  // land here with the slug in route.params.deepPath (see linking config in
  // App.js). Once the movie list has loaded, look it up and open it directly -
  // same as tapping the card would. Only acts once per app open.
  const deepLinkHandled = useRef(false);
  useEffect(() => {
    const slug = route?.params?.deepPath;
    if (!slug || deepLinkHandled.current || movies.length === 0) return;
    deepLinkHandled.current = true;
    const cleanSlug = slug.replace(/^\/+|\/+$/g, '');
    if (!cleanSlug) return;
    const liveMatch = movies.find(m => m.is_live && m.custom_slug === cleanSlug);
    if (liveMatch) { handleItemPress(liveMatch); return; }
    const movieMatch = movies.find(m => !m.is_live && !m.series_name && m.custom_slug === cleanSlug);
    if (movieMatch) { handleItemPress(movieMatch); return; }
    const epMatch = movies.find(m => m.series_name && m.custom_slug === cleanSlug);
    if (epMatch) { handleItemPress(seriesMap[epMatch.series_name]); return; }
  }, [route?.params?.deepPath, movies, seriesMap, handleItemPress]);

  const handlePlayDirect = useCallback(item => {
    const userId = user?.id || null;
    if (item.is_live) {
      navigation.navigate('Player', {
        movie: {
          ...item,
          is_live: true,
          type: item.type || 'direct',
          video_url: item.video_url || item.url || '',
          title: item.title || item.name || 'שידור חי',
        },
        userId,
      });
    } else {
      navigation.navigate('Player', {movie: item, startTime: 0, userId});
    }
  }, [navigation, user]);

  const handleHeroPlay = useCallback(movie => {
    const d = movie.series_name ? {...seriesMap[movie.series_name], thumbnail_url: movie.thumbnail_url, description: movie.description} : movie;
    showDonationModal(() => setDetailItem(d));
  }, [seriesMap, showDonationModal]);

  const handleHeroInfo = useCallback(movie => {
    const d = movie.series_name ? {...seriesMap[movie.series_name], thumbnail_url: movie.thumbnail_url, description: movie.description} : movie;
    showDonationModal(() => setDetailItem(d));
  }, [seriesMap, showDonationModal]);

  const handleSearchChange = useCallback(v => {
    if (v === ADMIN_TRIGGER) { setSearch(''); navigation.navigate('AdminEntry'); return; }
    setSearch(v);
    if (!v) setCategory('הכל');
  }, [navigation]);

  const onSearchFocus = useCallback(() => {
    Animated.timing(searchAnim, {toValue: 1, duration: 220, useNativeDriver: false}).start();
  }, [searchAnim]);

  const onSearchBlur = useCallback(() => {
    Animated.timing(searchAnim, {toValue: 0, duration: 220, useNativeDriver: false}).start();
  }, [searchAnim]);

  const searchBorderColor = searchAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ['rgba(255,255,255,0.08)', '#e50914'],
  });

  // ── First-launch sign-in screen ──
  if (!loading && showSignIn) {
    return (
      <View style={styles.signInScreen}>
        <Text style={styles.signInLogo}>ZOVEX</Text>
        <Text style={styles.signInTitle}>ברוכים הבאים</Text>
        <Text style={styles.signInSub}>כניסה לחשבון לחוויה מלאה</Text>
        <TouchableOpacity style={styles.googleBtn} onPress={startSignIn} activeOpacity={0.8}>
          <Text style={styles.googleBtnText}>🔑 כניסה עם Google</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.skipBtn}
          onPress={async () => {
            await AsyncStorage.setItem(SEEN_LOGIN_KEY, '1').catch(() => {});
            setShowSignIn(false);
          }}>
          <Text style={styles.skipBtnText}>המשך ללא כניסה</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#e50914" />
        <Text style={styles.loadingText}>טוען...</Text>
      </View>
    );
  }

  const isNetflixMode = category === 'הכל' && !search;
  const gridItems = isNetflixMode ? [] : getItemsForCategory(category);

  const TopBar = (
    <View style={styles.topBar}>
      <Text style={styles.appTitle}>ZOVEX</Text>

      <Animated.View style={[styles.searchWrapper, {borderColor: searchBorderColor}]}>
        <TextInput
          style={styles.searchInput}
          placeholder="חיפוש..."
          placeholderTextColor="rgba(255,255,255,0.3)"
          value={search}
          onChangeText={handleSearchChange}
          onFocus={onSearchFocus}
          onBlur={onSearchBlur}
          textAlign="right"
        />
      </Animated.View>

      {user ? (
        <TouchableOpacity onPress={() => setShowUserMenu(true)} style={styles.userBtn}>
          {user.picture ? (
            <Image source={{uri: user.picture}} style={styles.userAvatar} />
          ) : (
            <View style={styles.userAvatarFallback}>
              <Text style={{color: '#fff', fontSize: 13, fontWeight: '700'}}>
                {(user.given_name || user.name || '?')[0]}
              </Text>
            </View>
          )}
        </TouchableOpacity>
      ) : (
        <TouchableOpacity onPress={startSignIn} style={styles.signInBtn}>
          <Text style={styles.signInTxt}>כניסה</Text>
        </TouchableOpacity>
      )}
    </View>
  );

  const CatsButton = (
    <View style={styles.catsRow}>
      {category !== 'הכל' && (
        <TouchableOpacity
          onPress={() => { setCategory('הכל'); setSearch(''); }}
          style={styles.activeCatChip}>
          <Text style={styles.activeCatChipTxt}>✕  {category}</Text>
        </TouchableOpacity>
      )}
      <TouchableOpacity
        onPress={() => setShowCatModal(true)}
        style={styles.catsModalBtn}>
        <Text style={styles.catsModalBtnTxt}>≡  קטגוריות</Text>
      </TouchableOpacity>
    </View>
  );

  // ── Netflix-style category overlay ──
  const CatModal = (
    <Modal
      visible={showCatModal}
      transparent
      animationType="fade"
      onRequestClose={() => setShowCatModal(false)}>
      <View style={styles.catOverlay}>
        <ScrollView
          showsVerticalScrollIndicator={false}
          contentContainerStyle={styles.catScrollContent}>
          {allCategories.map(c => (
            <TouchableOpacity
              key={c}
              onPress={() => { setCategory(c); setSearch(''); setShowCatModal(false); }}
              style={styles.catOverlayItem}
              activeOpacity={0.65}>
              <Text style={[styles.catOverlayText, category === c && styles.catOverlayTextActive]}>
                {c}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
        <TouchableOpacity style={styles.catCloseBtn} onPress={() => setShowCatModal(false)} activeOpacity={0.85}>
          <Text style={styles.catCloseTxt}>✕</Text>
        </TouchableOpacity>
      </View>
    </Modal>
  );

  // ── User menu modal ──
  const UserMenu = (
    <Modal
      visible={showUserMenu}
      transparent
      animationType="fade"
      onRequestClose={() => setShowUserMenu(false)}>
      <TouchableOpacity
        style={styles.modalOverlay}
        activeOpacity={1}
        onPress={() => setShowUserMenu(false)}>
        <View style={styles.userMenuBox} onStartShouldSetResponder={() => true}>
          {user?.picture ? (
            <Image source={{uri: user.picture}} style={styles.menuAvatar} />
          ) : (
            <View style={styles.menuAvatarFallback}>
              <Text style={{color:'#fff', fontSize:22, fontWeight:'800'}}>
                {(user?.given_name || user?.name || '?')[0]}
              </Text>
            </View>
          )}
          <Text style={styles.menuName}>{user?.name || user?.given_name || ''}</Text>
          <Text style={styles.menuEmail}>{user?.email || ''}</Text>
          <View style={styles.menuDivider} />
          <TouchableOpacity
            style={styles.menuItem}
            onPress={() => { setShowUserMenu(false); setCategory('היסטוריה'); setSearch(''); }}>
            <Text style={styles.menuItemText}>📋  היסטוריית צפייה</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.menuItem}
            onPress={() => { setShowUserMenu(false); signOut(); }}>
            <Text style={[styles.menuItemText, {color: '#e50914'}]}>🚪  יציאה מהחשבון</Text>
          </TouchableOpacity>
        </View>
      </TouchableOpacity>
    </Modal>
  );

  return (
    <View style={styles.container}>
      {TopBar}
      {CatsButton}
      {isNetflixMode ? (
        // A plain ScrollView mounted every category row (and its images) at
        // once, even ones far below the fold - with dozens of categories
        // that's a lot of images fetched on every app open. A vertical
        // FlatList only mounts rows near the viewport, same idea as the
        // existing per-row virtualization below.
        <FlatList
          data={netflixRows}
          keyExtractor={row => row.title}
          renderItem={({item: row}) => (
            <NetflixRow title={row.title} items={row.items} isLiveRow={row.isLiveRow} onPress={handleItemPress} />
          )}
          ListHeaderComponent={<HeroBanner movies={movies} onPlay={handleHeroPlay} onInfo={handleHeroInfo} />}
          ListEmptyComponent={<Text style={styles.empty}>אין תוכן זמין</Text>}
          showsVerticalScrollIndicator={false}
          removeClippedSubviews
          initialNumToRender={3}
          maxToRenderPerBatch={2}
          windowSize={5}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => load(true, user)} tintColor="#e50914" />
          }
        />
      ) : (
        <FlatList
            data={gridItems}
            keyExtractor={item => String(item.id)}
            numColumns={3}
            contentContainerStyle={styles.grid}
            initialNumToRender={9}
            maxToRenderPerBatch={9}
            windowSize={5}
            removeClippedSubviews
            refreshControl={
              <RefreshControl refreshing={refreshing} onRefresh={() => load(true, user)} tintColor="#e50914" />
            }
            renderItem={({item}) => <MovieCard item={item} onPress={handleItemPress} />}
            ListEmptyComponent={
              category === 'היסטוריה' ? (
                <View style={styles.historyEmpty}>
                  <Text style={styles.historyEmptyTitle}>עדיין לא צפית בשום דבר</Text>
                  <Text style={styles.historyEmptyDesc}>ההיסטוריה שלך תופיע כאן</Text>
                </View>
              ) : category === DOWNLOADS_CATEGORY ? (
                <View style={styles.historyEmpty}>
                  <Text style={styles.historyEmptyTitle}>עדיין לא הורדת שום דבר</Text>
                  <Text style={styles.historyEmptyDesc}>הורידו סרטים וסדרות ממסך הפרטים כדי לצפות גם בלי אינטרנט</Text>
                </View>
              ) : (
                <Text style={styles.empty}>לא נמצאו תוצאות</Text>
              )
            }
          />
      )}

      {detailItem && (
        <MovieDetailModal
          item={detailItem}
          allMovies={movies}
          onClose={() => setDetailItem(null)}
          onPlayDirect={handlePlayDirect}
          downloadedIds={downloadedIds}
          downloadingId={downloadingId}
          downloadProgress={downloadProgress}
          onDownload={handleDownloadItem}
          onDeleteDownload={handleDeleteDownload}
        />
      )}

      {preparingPlaybackId && (
        <View style={styles.prepOverlay}>
          <ActivityIndicator size="large" color="#e50914" />
          <Text style={styles.prepTxt}>מכין לצפייה...</Text>
        </View>
      )}

      {CatModal}
      {UserMenu}

      {/* Telegram floating bubble */}
      <View style={styles.tgBubbleWrap} pointerEvents="box-none">
        {showTgTip && (
          <View style={styles.tgTip}>
            <TouchableOpacity
              style={styles.tgTipClose}
              onPress={() => {
                setShowTgTip(false);
                AsyncStorage.setItem(TG_TIP_KEY, '1').catch(() => {});
              }}
              hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}>
              <Text style={styles.tgTipCloseTxt}>✕</Text>
            </TouchableOpacity>
            <Text style={styles.tgTipTitle}>לחצו כאן לתמיכה 💬</Text>
            <Text style={styles.tgTipSub}>או להוספת סרט חדש</Text>
          </View>
        )}
        <TouchableOpacity
          style={styles.tgBtn}
          activeOpacity={0.85}
          onPress={() => Linking.openURL('https://t.me/ZOVE8').catch(() => {})}>
          <Text style={styles.tgBtnIcon}>➤</Text>
          <Text style={styles.tgBtnLabel}>תמיכה</Text>
        </TouchableOpacity>
      </View>

      <Modal
        visible={showDonation}
        transparent
        animationType="fade"
        onRequestClose={() => { setShowDonation(false); donationCallback.current = null; }}>
        <View style={styles.donOverlay}>
          <View style={styles.donCard}>
            <Text style={styles.donEmoji}>🎬</Text>
            <Text style={styles.donTitle}>עזרו לנו לשפר את האפליקציה</Text>
            <Text style={styles.donBody}>
              {'ZOVEX פועל ללא מטרות רווח ובהתנדבות מלאה.\nתרומה קטנה תעזור לנו לשפר את איכות האפליקציה,\nלשדרג את הנגנים ולהוסיף עוד תכנים כיפיים לצפייה 💙'}
            </Text>
            <TouchableOpacity
              style={styles.donBitBtn}
              activeOpacity={0.85}
              onPress={() => Linking.openURL('https://www.bitpay.co.il/app/me/F062649F-7124-4CDF-88DD-A1FEA14185EB').catch(() => {})}>
              <Text style={styles.donBitTxt}>💳 תרום בביט</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.donContinueBtn}
              activeOpacity={0.85}
              onPress={handleDonationContinue}>
              <Text style={styles.donContinueTxt}>המשך לצפייה</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0a0a0a'},
  center: {flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#0a0a0a'},
  loadingText: {color: '#aaa', marginTop: 12, fontSize: 14},

  // ── First-launch sign-in screen ──
  signInScreen: {
    flex: 1, backgroundColor: '#0a0a0a', justifyContent: 'center',
    alignItems: 'center', paddingHorizontal: 32,
  },
  signInLogo: {color: '#e50914', fontSize: 42, fontWeight: '900', letterSpacing: 8, marginBottom: 28},
  signInTitle: {color: '#fff', fontSize: 26, fontWeight: '800', marginBottom: 8},
  signInSub: {color: '#666', fontSize: 14, marginBottom: 40, textAlign: 'center'},
  googleBtn: {
    width: '100%', backgroundColor: '#4285f4', borderRadius: 14,
    paddingVertical: 16, alignItems: 'center', marginBottom: 14,
  },
  googleBtnText: {color: '#fff', fontSize: 16, fontWeight: '700'},
  skipBtn: {paddingVertical: 12, paddingHorizontal: 24},
  skipBtnText: {color: '#555', fontSize: 14},

  // ── Top bar ──
  topBar: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 16, paddingTop: 14, paddingBottom: 8,
  },
  appTitle: {color: '#e50914', fontSize: 22, fontWeight: '900', letterSpacing: 6},
  signInBtn: {
    backgroundColor: '#1a1a1a', borderWidth: 1, borderColor: '#333',
    borderRadius: 18, paddingHorizontal: 14, paddingVertical: 7,
  },
  signInTxt: {color: '#fff', fontSize: 13, fontWeight: '700'},
  userBtn: {padding: 2},
  userAvatar: {width: 34, height: 34, borderRadius: 17},
  userAvatarFallback: {
    width: 34, height: 34, borderRadius: 17, backgroundColor: '#e50914',
    justifyContent: 'center', alignItems: 'center',
  },

  // ── HeroBanner ──
  hero: {width: '100%', height: HERO_H, backgroundColor: '#0a0a0a'},
  heroBg: {width: '100%', height: HERO_H, justifyContent: 'flex-end'},
  heroGradient: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.3)',
  },
  heroContent: {padding: 16, paddingBottom: 36},
  heroTitle: {
    color: '#fff', fontSize: 26, fontWeight: '900', textAlign: 'right',
    textShadowColor: 'rgba(0,0,0,0.8)', textShadowOffset: {width: 0, height: 2},
    textShadowRadius: 8, marginBottom: 6,
  },
  heroDesc: {
    color: 'rgba(255,255,255,0.82)', fontSize: 13, textAlign: 'right',
    lineHeight: 20, marginBottom: 14,
    textShadowColor: 'rgba(0,0,0,0.6)', textShadowOffset: {width: 0, height: 1}, textShadowRadius: 4,
  },
  heroBtns: {flexDirection: 'row', justifyContent: 'flex-end', gap: 10},
  heroBtnPlay: {backgroundColor: '#fff', paddingVertical: 10, paddingHorizontal: 22, borderRadius: 8},
  heroBtnPlayText: {color: '#000', fontSize: 15, fontWeight: '800'},
  heroBtnInfo: {backgroundColor: 'rgba(100,100,110,0.55)', paddingVertical: 10, paddingHorizontal: 18, borderRadius: 8},
  heroBtnInfoText: {color: '#fff', fontSize: 15, fontWeight: '700'},
  heroDots: {position: 'absolute', bottom: 8, left: 0, right: 0, flexDirection: 'row', justifyContent: 'center', gap: 5},
  heroDot: {width: 6, height: 6, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.35)'},
  heroDotActive: {backgroundColor: '#fff', width: 18},

  // ── Top bar search ──
  searchWrapper: {
    flex: 1, marginHorizontal: 10, borderRadius: 20, borderWidth: 1,
    backgroundColor: 'rgba(255,255,255,0.06)', overflow: 'hidden',
  },
  searchInput: {
    color: '#fff', fontSize: 14, paddingHorizontal: 14, paddingVertical: 8,
  },

  // ── Category button row ──
  catsRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end',
    paddingHorizontal: 14, paddingBottom: 6, gap: 8,
  },
  activeCatChip: {
    backgroundColor: 'rgba(229,9,20,0.18)', borderWidth: 1, borderColor: '#e50914',
    borderRadius: 20, paddingHorizontal: 12, paddingVertical: 6,
  },
  activeCatChipTxt: {color: '#e50914', fontSize: 13, fontWeight: '700'},
  catsModalBtn: {
    backgroundColor: '#1a1a1a', borderWidth: 1, borderColor: '#333',
    borderRadius: 20, paddingHorizontal: 14, paddingVertical: 7,
  },
  catsModalBtnTxt: {color: '#ccc', fontSize: 13, fontWeight: '600'},

  // ── Modal shared ──
  modalOverlay: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.6)',
    justifyContent: 'center', alignItems: 'center',
  },

  // ── Netflix-style category overlay ──
  catOverlay: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.88)',
    alignItems: 'center',
  },
  catScrollContent: {
    alignItems: 'center', paddingTop: 60, paddingBottom: 120, width: SW,
  },
  catOverlayItem: {
    paddingVertical: 14, paddingHorizontal: 40, width: SW, alignItems: 'center',
  },
  catOverlayText: {
    color: 'rgba(255,255,255,0.45)', fontSize: 22, fontWeight: '400', textAlign: 'center',
  },
  catOverlayTextActive: {
    color: '#fff', fontSize: 26, fontWeight: '800',
  },
  catCloseBtn: {
    position: 'absolute', bottom: 40,
    width: 58, height: 58, borderRadius: 29,
    backgroundColor: '#fff',
    justifyContent: 'center', alignItems: 'center',
  },
  catCloseTxt: {color: '#000', fontSize: 22, fontWeight: '700'},

  // ── User menu modal ──
  userMenuBox: {
    backgroundColor: '#1a1a1a', borderRadius: 20, width: SW * 0.76,
    paddingVertical: 22, paddingHorizontal: 20, alignItems: 'center',
  },
  menuAvatar: {width: 64, height: 64, borderRadius: 32, marginBottom: 10},
  menuAvatarFallback: {
    width: 64, height: 64, borderRadius: 32, backgroundColor: '#e50914',
    justifyContent: 'center', alignItems: 'center', marginBottom: 10,
  },
  menuName: {color: '#fff', fontSize: 16, fontWeight: '800', marginBottom: 2},
  menuEmail: {color: '#888', fontSize: 12, marginBottom: 14},
  menuDivider: {width: '100%', height: 1, backgroundColor: '#2a2a2a', marginBottom: 10},
  menuItem: {width: '100%', paddingVertical: 14, alignItems: 'center'},
  menuItemText: {color: '#e5e5e5', fontSize: 15, fontWeight: '600'},

  // ── Netflix rows ──
  rowWrap: {marginBottom: 24},
  rowHeader: {flexDirection: 'row', alignItems: 'center', paddingHorizontal: 14, marginBottom: 10, justifyContent: 'flex-end'},
  liveIcon: {color: '#e50914', fontSize: 10, marginLeft: 6},
  rowTitle: {color: '#fff', fontSize: 16, fontWeight: '800', textAlign: 'right'},
  rowList: {paddingHorizontal: 10},

  // ── Card ──
  card: {marginHorizontal: 5, borderRadius: 10, overflow: 'hidden'},
  cardImg: {width: '100%', borderRadius: 10, overflow: 'hidden', backgroundColor: '#1c1c1e'},
  cardImgInner: {width: '100%', height: '100%', resizeMode: 'cover'},
  noThumb: {width: '100%', height: '100%', justifyContent: 'center', alignItems: 'center', backgroundColor: '#1c1c1e'},
  thumbEmoji: {fontSize: 28},
  cardTitle: {color: '#f2f2f2', fontSize: 11, fontWeight: '700', paddingTop: 5, paddingHorizontal: 2, textAlign: 'right'},
  badge: {position: 'absolute', top: 7, right: 7, backgroundColor: 'rgba(0,0,0,0.65)', borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2},
  liveBadge: {backgroundColor: '#e50914'},
  badgeText: {color: '#fff', fontSize: 9, fontWeight: '800'},

  // ── Grid ──
  grid: {paddingHorizontal: 8, paddingBottom: 20, paddingTop: 4},
  empty: {color: '#555', textAlign: 'center', marginTop: 60, fontSize: 16},
  historyEmpty: {alignItems: 'center', marginTop: 80, paddingHorizontal: 30},
  historyEmptyTitle: {color: '#aaa', fontSize: 18, fontWeight: '600', marginBottom: 8},
  historyEmptyDesc: {color: '#555', fontSize: 13, textAlign: 'center'},

  // ── Offline-download playback prep overlay ──
  prepOverlay: {
    ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.85)',
    justifyContent: 'center', alignItems: 'center', zIndex: 500,
  },
  prepTxt: {color: '#ccc', fontSize: 14, marginTop: 12},

  // ── Telegram floating bubble ──
  // React Native mirrors absolute left/right positioning when the device
  // locale is RTL (unlike CSS on the web, where "left" always means the
  // physical left edge). Pick the side explicitly so this always ends up
  // in the bottom-left corner of the screen, regardless of RTL state.
  tgBubbleWrap: {
    position: 'absolute', bottom: 20, zIndex: 1000,
    flexDirection: 'row', alignItems: 'flex-end', gap: 8,
    ...(I18nManager.isRTL ? {right: 14} : {left: 14}),
  },
  tgTip: {
    position: 'relative', backgroundColor: 'rgba(26,26,26,0.92)',
    borderRadius: 14, borderBottomLeftRadius: 4,
    padding: 8, paddingRight: 24, maxWidth: 150,
    shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 5,
    elevation: 6,
  },
  tgTipClose: {position: 'absolute', top: 3, right: 4, padding: 2},
  tgTipCloseTxt: {color: '#777', fontSize: 10, fontWeight: '700'},
  tgTipTitle: {color: '#eee', fontSize: 11, fontWeight: '700', marginBottom: 2},
  tgTipSub: {color: '#888', fontSize: 10, lineHeight: 14},
  tgBtn: {
    height: 42, paddingHorizontal: 14, borderRadius: 21,
    backgroundColor: '#229ED9',
    flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 6,
    shadowColor: '#229ED9', shadowOpacity: 0.45, shadowRadius: 6,
    elevation: 8,
  },
  tgBtnIcon: {color: '#fff', fontSize: 16},
  tgBtnLabel: {color: '#fff', fontSize: 12, fontWeight: '700'},

  // ── Donation modal ──
  donOverlay: {flex: 1, backgroundColor: 'rgba(0,0,0,0.88)', justifyContent: 'center', alignItems: 'center', padding: 20},
  donCard: {backgroundColor: '#111', borderRadius: 24, padding: 28, width: '100%', alignItems: 'center', borderWidth: 1, borderColor: '#222'},
  donEmoji: {fontSize: 32, marginBottom: 10},
  donTitle: {fontSize: 20, fontWeight: '900', color: '#fff', textAlign: 'center', marginBottom: 10},
  donBody: {fontSize: 14, color: '#aaa', textAlign: 'center', lineHeight: 24, marginBottom: 20},
  donBitBtn: {width: '100%', backgroundColor: '#0d7a5f', borderRadius: 14, paddingVertical: 16, alignItems: 'center', marginBottom: 10},
  donBitTxt: {color: '#fff', fontSize: 16, fontWeight: '700'},
  donContinueBtn: {width: '100%', backgroundColor: '#1e1e1e', borderRadius: 14, paddingVertical: 14, alignItems: 'center', borderWidth: 1, borderColor: '#333'},
  donContinueTxt: {color: '#888', fontSize: 14},
});
