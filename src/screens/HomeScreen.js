import React, {useEffect, useState, useMemo, useCallback, useRef, memo} from 'react';
import {
  View,
  Text,
  Alert,
  Modal,
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
} from 'react-native';
import {GoogleSignin} from '@react-native-google-signin/google-signin';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  fetchMovies,
  fetchLiveChannels,
  fetchHistory,
  loadProgress,
  clearCache,
} from '../api/movies';
import {getUserId} from '../api/userStore';

const {width: SW} = Dimensions.get('window');
// 3 cards + 5px margin each side + 8px grid padding each side = 3*CARD_W + 30 + 16 = SW
const CARD_W = Math.floor((SW - 46) / 3);
const CARD_H = Math.floor(CARD_W * 1.48);
// Hero banner: tall enough to show portrait thumbnails (2:3) with contain mode
const HERO_H = Math.round(SW * 1.25);

const ADMIN_TRIGGER = 'ZovexAdmin2026';
const USER_KEY = 'zovex_google_user';
const SEEN_LOGIN_KEY = 'zovex_seen_login';

GoogleSignin.configure({
  scopes: ['profile', 'email'],
  offlineAccess: false,
});

// ── Movie Detail Modal ────────────────────────────────────────────────────────

function MovieDetailModal({item, allMovies, onClose, onPlayDirect}) {
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
            <TouchableOpacity style={mdStyles.playBtn} activeOpacity={0.8} onPress={() => onPlayDirect(firstEp || item)}>
              <Text style={mdStyles.playTxt}>▶ הפעל</Text>
            </TouchableOpacity>
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
  playBtn: {backgroundColor: '#e50914', borderRadius: 12, paddingVertical: 14, alignItems: 'center'},
  playTxt: {color: '#fff', fontSize: 16, fontWeight: '800'},
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
    const seen = {};
    const result = movies.filter(m => {
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

export default function HomeScreen({navigation}) {
  const [movies, setMovies] = useState([]);
  const [liveChannels, setLiveChannels] = useState([]);
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
  const searchAnim = useRef(new Animated.Value(0)).current;

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

  // ── Data loading ──
  const load = useCallback(async (refresh = false, loggedInUser = null) => {
    if (refresh) { clearCache(); setRefreshing(true); }
    try {
      const [data, live, hist] = await Promise.all([
        fetchMovies(),
        fetchLiveChannels(),
        loggedInUser ? fetchHistory(loggedInUser.id) : Promise.resolve([]),
      ]);
      setMovies(data);
      setLiveChannels(live);
      setHistory(hist);
    } catch {}
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { load(false, user); }, [load, user]);

  // Clear detail modal when returning from Player so no flash on back-navigate
  useEffect(() => {
    const unsub = navigation.addListener('focus', () => setDetailItem(null));
    return unsub;
  }, [navigation]);

  const seriesMap = useMemo(() => buildSeriesMap(movies), [movies]);

  const allCategories = useMemo(() => {
    const cats = [...new Set(movies.map(m => m.category).filter(Boolean))];
    const tabs = ['הכל'];
    if (liveChannels.length > 0) tabs.push('שידורים חיים');
    tabs.push(...cats);
    tabs.push('היסטוריה');
    return tabs;
  }, [movies, liveChannels]);

  const q = useMemo(() => search.toLowerCase(), [search]);

  const getItemsForCategory = useCallback(cat => {
    if (cat === 'שידורים חיים') {
      return liveChannels
        .filter(ch => (ch.title || ch.name || '').toLowerCase().includes(q))
        .map(ch => ({...ch, is_live: true, id: ch.id || ch.name}));
    }
    if (cat === 'היסטוריה') {
      return history.map(h => movies.find(m => m.id === h.media_id)).filter(Boolean);
    }
    const seen = {};
    const result = [];
    movies.forEach(m => {
      const matchQ = (m.title||'').toLowerCase().includes(q) || (m.series_name||'').toLowerCase().includes(q);
      if (!matchQ || (cat !== 'הכל' && m.category !== cat)) return;
      if (m.series_name) {
        if (!seen[m.series_name]) { seen[m.series_name] = true; result.push({...seriesMap[m.series_name]}); }
      } else {
        result.push({...m, isSeries: false});
      }
    });
    return result;
  }, [movies, liveChannels, history, seriesMap, q]);

  const netflixRows = useMemo(() => {
    const rows = [];
    const liveMov = movies.filter(m => m.is_live);
    const allLiveItems = [
      ...liveChannels.map(ch => ({...ch, is_live: true, id: ch.id || ch.name})),
      ...liveMov.filter(m => !liveChannels.find(ch => (ch.id || ch.name) === m.id)),
    ];
    if (allLiveItems.length > 0)
      rows.push({title: 'שידורים חיים', isLiveRow: true, items: allLiveItems});
    const histItems = history.map(h => movies.find(m => m.id === h.media_id)).filter(Boolean);
    if (histItems.length > 0) rows.push({title: '▶ המשך צפייה', items: histItems});
    allCategories
      .filter(c => c !== 'הכל' && c !== 'שידורים חיים' && c !== 'היסטוריה')
      .forEach(cat => {
        const items = getItemsForCategory(cat);
        if (items.length > 0) rows.push({title: cat, items});
      });
    return rows;
  }, [liveChannels, history, movies, allCategories, getItemsForCategory]);

  const handleItemPress = useCallback(item => {
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
  }, [navigation, user]);

  const handlePlayDirect = useCallback(async item => {
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
      const startTime = userId ? await loadProgress(item.id, userId) : 0;
      navigation.navigate('Player', {movie: item, startTime: startTime || 0, userId});
    }
  }, [navigation, user]);

  const handleHeroPlay = useCallback(movie => {
    setDetailItem(movie.series_name ? {...seriesMap[movie.series_name], thumbnail_url: movie.thumbnail_url, description: movie.description} : movie);
  }, [seriesMap]);

  const handleHeroInfo = useCallback(movie => {
    setDetailItem(movie.series_name ? {...seriesMap[movie.series_name], thumbnail_url: movie.thumbnail_url, description: movie.description} : movie);
  }, [seriesMap]);

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
        <ScrollView
          showsVerticalScrollIndicator={false}
          removeClippedSubviews
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => load(true, user)} tintColor="#e50914" />
          }>
          <HeroBanner movies={movies} onPlay={handleHeroPlay} onInfo={handleHeroInfo} />
          {netflixRows.map(row => (
            <NetflixRow key={row.title} title={row.title} items={row.items} isLiveRow={row.isLiveRow} onPress={handleItemPress} />
          ))}
          {netflixRows.length === 0 && <Text style={styles.empty}>אין תוכן זמין</Text>}
        </ScrollView>
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
        />
      )}

      {CatModal}
      {UserMenu}
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
});
