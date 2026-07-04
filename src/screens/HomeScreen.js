import React, {useEffect, useState, useMemo, useCallback, useRef} from 'react';
import {
  View,
  Text,
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
  Modal,
} from 'react-native';
import {WebView} from 'react-native-webview';
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
const CARD_W = SW * 0.32;
const CARD_H = CARD_W * 1.48;

const ANDROID_CLIENT_ID =
  '1095467813314-d3fn8ad1roao5qk3gtilg9hhq8drn85v.apps.googleusercontent.com';
const REDIRECT_URI =
  'com.googleusercontent.apps.1095467813314-d3fn8ad1roao5qk3gtilg9hhq8drn85v:/oauth2redirect/google';

// ── Google Sign-In Modal ──────────────────────────────────────────────────────

function GoogleSignInModal({visible, onSuccess, onClose}) {
  const codeVerifierRef = useRef('');
  const handledRef = useRef(false);

  const authUrl = useMemo(() => {
    if (!visible) return '';
    handledRef.current = false;
    const chars =
      'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';
    let cv = '';
    for (let i = 0; i < 64; i++)
      cv += chars[Math.floor(Math.random() * chars.length)];
    codeVerifierRef.current = cv;
    const params = [
      `client_id=${encodeURIComponent(ANDROID_CLIENT_ID)}`,
      `redirect_uri=${encodeURIComponent(REDIRECT_URI)}`,
      'response_type=code',
      `scope=${encodeURIComponent('openid profile email')}`,
      `code_challenge=${encodeURIComponent(cv)}`,
      'code_challenge_method=plain',
      'prompt=select_account',
    ].join('&');
    return `https://accounts.google.com/o/oauth2/v2/auth?${params}`;
  }, [visible]);

  const handleRedirect = useCallback(
    async url => {
      if (handledRef.current) return;
      if (!url || !url.startsWith('com.googleusercontent.apps.')) return;
      handledRef.current = true;
      try {
        const m = url.match(/[?&]code=([^&\s#]+)/);
        if (!m) {
          onClose();
          return;
        }
        const code = decodeURIComponent(m[1]);
        const cv = codeVerifierRef.current;
        const tokenRes = await fetch('https://oauth2.googleapis.com/token', {
          method: 'POST',
          headers: {'Content-Type': 'application/x-www-form-urlencoded'},
          body: [
            `code=${encodeURIComponent(code)}`,
            `client_id=${encodeURIComponent(ANDROID_CLIENT_ID)}`,
            `redirect_uri=${encodeURIComponent(REDIRECT_URI)}`,
            'grant_type=authorization_code',
            `code_verifier=${encodeURIComponent(cv)}`,
          ].join('&'),
        });
        const tokens = await tokenRes.json();
        if (tokens.access_token) {
          const userRes = await fetch(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            {headers: {Authorization: `Bearer ${tokens.access_token}`}},
          );
          const userInfo = await userRes.json();
          onSuccess(userInfo);
        } else {
          onClose();
        }
      } catch {
        onClose();
      }
    },
    [onSuccess, onClose],
  );

  if (!visible) return null;

  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <View style={gsiStyles.container}>
        <View style={gsiStyles.header}>
          <TouchableOpacity onPress={onClose}>
            <Text style={gsiStyles.closeTxt}>✕</Text>
          </TouchableOpacity>
          <Text style={gsiStyles.title}>כניסה עם Google</Text>
          <View style={{width: 36}} />
        </View>
        <WebView
          source={{uri: authUrl}}
          onShouldStartLoadWithRequest={req => {
            if (req.url.startsWith('com.googleusercontent.apps.')) {
              handleRedirect(req.url);
              return false;
            }
            return true;
          }}
          onNavigationStateChange={state => {
            if (
              state.url &&
              state.url.startsWith('com.googleusercontent.apps.')
            ) {
              handleRedirect(state.url);
            }
          }}
          javaScriptEnabled
          domStorageEnabled
        />
      </View>
    </Modal>
  );
}

const gsiStyles = StyleSheet.create({
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
  closeTxt: {color: '#aaa', fontSize: 20, padding: 4},
  title: {color: '#fff', fontSize: 16, fontWeight: '700'},
});

// ── Movie Detail Modal ────────────────────────────────────────────────────────

function MovieDetailModal({item, allMovies, onClose, onPlayDirect}) {
  const episodes = useMemo(() => {
    if (!item?.series_name) return [];
    return allMovies
      .filter(m => m.series_name === item.series_name)
      .sort((a, b) => {
        const sa = a.season_number || 1,
          sb = b.season_number || 1;
        if (sa !== sb) return sa - sb;
        return (a.episode_number || 0) - (b.episode_number || 0);
      });
  }, [item, allMovies]);

  if (!item) return null;

  const displayTitle = item.series_name || item.title || item.name || '';
  const firstEp = episodes.length > 0 ? episodes[0] : null;

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={mdStyles.overlay}>
        <TouchableOpacity
          style={StyleSheet.absoluteFillObject}
          onPress={onClose}
          activeOpacity={1}
        />
        <View style={mdStyles.sheet}>
          <TouchableOpacity style={mdStyles.closeBtn} onPress={onClose}>
            <Text style={mdStyles.closeTxt}>✕</Text>
          </TouchableOpacity>
          <ScrollView showsVerticalScrollIndicator={false} bounces={false}>
            {item.thumbnail_url ? (
              <Image source={{uri: item.thumbnail_url}} style={mdStyles.thumb} />
            ) : (
              <View style={mdStyles.noThumb}>
                <Text style={{fontSize: 52}}>
                  {item.is_live ? '📡' : '🎬'}
                </Text>
              </View>
            )}
            <View style={mdStyles.body}>
              <Text style={mdStyles.title}>{displayTitle}</Text>
              {!!item.description && (
                <Text style={mdStyles.desc} numberOfLines={5}>
                  {item.description}
                </Text>
              )}
              <TouchableOpacity
                style={mdStyles.playBtn}
                activeOpacity={0.8}
                onPress={() => onPlayDirect(firstEp || item)}>
                <Text style={mdStyles.playTxt}>▶ הפעל</Text>
              </TouchableOpacity>
            </View>

            {episodes.length > 1 && (
              <View style={mdStyles.epsSection}>
                <Text style={mdStyles.epsHeader}>
                  פרקים ({episodes.length})
                </Text>
                {episodes.map(ep => (
                  <TouchableOpacity
                    key={ep.id}
                    style={mdStyles.epRow}
                    activeOpacity={0.75}
                    onPress={() => onPlayDirect(ep)}>
                    {ep.thumbnail_url ? (
                      <Image
                        source={{uri: ep.thumbnail_url}}
                        style={mdStyles.epThumb}
                      />
                    ) : (
                      <View style={mdStyles.epThumbEmpty}>
                        <Text style={{fontSize: 16, color: '#aaa'}}>▶</Text>
                      </View>
                    )}
                    <View style={mdStyles.epInfo}>
                      <Text style={mdStyles.epNum}>
                        {ep.season_number
                          ? `עונה ${ep.season_number} · `
                          : ''}
                        פרק {ep.episode_number}
                      </Text>
                      <Text style={mdStyles.epTitle} numberOfLines={2}>
                        {ep.episode_title || ep.title}
                      </Text>
                    </View>
                    <Text style={mdStyles.epPlayIcon}>▶</Text>
                  </TouchableOpacity>
                ))}
              </View>
            )}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const mdStyles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: '#111',
    borderTopLeftRadius: 22,
    borderTopRightRadius: 22,
    maxHeight: '88%',
    overflow: 'hidden',
  },
  closeBtn: {
    position: 'absolute',
    top: 12,
    right: 14,
    zIndex: 10,
    backgroundColor: 'rgba(0,0,0,0.55)',
    borderRadius: 16,
    width: 32,
    height: 32,
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeTxt: {color: '#fff', fontSize: 14, fontWeight: '700'},
  thumb: {width: '100%', height: 210, resizeMode: 'cover'},
  noThumb: {
    width: '100%',
    height: 180,
    backgroundColor: '#1c1c1e',
    justifyContent: 'center',
    alignItems: 'center',
  },
  body: {padding: 18},
  title: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '800',
    textAlign: 'right',
    marginBottom: 8,
  },
  desc: {
    color: '#aaa',
    fontSize: 13,
    lineHeight: 20,
    textAlign: 'right',
    marginBottom: 16,
  },
  playBtn: {
    backgroundColor: '#e50914',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  playTxt: {color: '#fff', fontSize: 16, fontWeight: '800'},
  epsSection: {paddingHorizontal: 16, paddingBottom: 24},
  epsHeader: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '800',
    textAlign: 'right',
    marginBottom: 10,
    borderTopWidth: 1,
    borderTopColor: '#222',
    paddingTop: 14,
  },
  epRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#1a1a1a',
  },
  epThumb: {width: 110, height: 62, borderRadius: 6, resizeMode: 'cover'},
  epThumbEmpty: {
    width: 110,
    height: 62,
    borderRadius: 6,
    backgroundColor: '#222',
    justifyContent: 'center',
    alignItems: 'center',
  },
  epInfo: {flex: 1, marginHorizontal: 10},
  epNum: {
    color: '#e50914',
    fontSize: 11,
    fontWeight: '700',
    textAlign: 'right',
  },
  epTitle: {
    color: '#f2f2f2',
    fontSize: 13,
    fontWeight: '600',
    textAlign: 'right',
    marginTop: 3,
  },
  epPlayIcon: {color: '#e50914', fontSize: 14},
});

// ── HeroBanner ────────────────────────────────────────────────────────────────

function HeroBanner({movies, onPlay, onInfo}) {
  const heroMovies = useMemo(() => {
    const now = Date.now();
    const DAY = 24 * 60 * 60 * 1000;
    const seen = {};
    return movies
      .filter(m => {
        if (!m.created_date) return false;
        const t = new Date(m.created_date).getTime();
        if (isNaN(t) || now - t > DAY) return false;
        if (m.series_name) {
          if (seen[m.series_name]) return false;
          seen[m.series_name] = true;
        }
        return true;
      })
      .sort((a, b) => new Date(b.created_date) - new Date(a.created_date))
      .slice(0, 6);
  }, [movies]);

  const [index, setIndex] = useState(0);
  const fadeAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (heroMovies.length < 2) return;
    const t = setInterval(() => {
      Animated.timing(fadeAnim, {
        toValue: 0,
        duration: 400,
        useNativeDriver: true,
      }).start(() => {
        setIndex(i => (i + 1) % heroMovies.length);
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 400,
          useNativeDriver: true,
        }).start();
      });
    }, 10000);
    return () => clearInterval(t);
  }, [heroMovies.length, fadeAnim]);

  if (heroMovies.length === 0) return null;

  const movie = heroMovies[index];

  return (
    <Animated.View style={[styles.hero, {opacity: fadeAnim}]}>
      {movie.thumbnail_url ? (
        <ImageBackground
          source={{uri: movie.thumbnail_url}}
          style={styles.heroBg}
          resizeMode="cover">
          <View style={styles.heroGradient} />
          <View style={styles.heroContent}>
            <Text style={styles.heroTitle} numberOfLines={2}>
              {movie.series_name || movie.title}
            </Text>
            {!!movie.description && (
              <Text style={styles.heroDesc} numberOfLines={2}>
                {movie.description}
              </Text>
            )}
            <View style={styles.heroBtns}>
              <TouchableOpacity
                style={styles.heroBtnPlay}
                activeOpacity={0.8}
                onPress={() => onPlay(movie)}>
                <Text style={styles.heroBtnPlayText}>▶ צפה</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.heroBtnInfo}
                activeOpacity={0.8}
                onPress={() => onInfo(movie)}>
                <Text style={styles.heroBtnInfoText}>מידע נוסף</Text>
              </TouchableOpacity>
            </View>
          </View>
        </ImageBackground>
      ) : (
        <View style={[styles.heroBg, {backgroundColor: '#111'}]}>
          <View style={styles.heroContent}>
            <Text style={styles.heroTitle}>
              {movie.series_name || movie.title}
            </Text>
            <View style={styles.heroBtns}>
              <TouchableOpacity
                style={styles.heroBtnPlay}
                activeOpacity={0.8}
                onPress={() => onPlay(movie)}>
                <Text style={styles.heroBtnPlayText}>▶ צפה</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      )}
      {heroMovies.length > 1 && (
        <View style={styles.heroDots}>
          {heroMovies.map((_, i) => (
            <View
              key={i}
              style={[styles.heroDot, i === index && styles.heroDotActive]}
            />
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
        episodes: [],
      };
    }
    map[m.series_name].episodes.push(m);
  });
  return map;
}

// ── MovieCard ─────────────────────────────────────────────────────────────────

function MovieCard({item, onPress}) {
  const isLive = !!item.is_live;
  return (
    <TouchableOpacity
      style={[styles.card, {width: CARD_W}]}
      onPress={() => onPress(item)}
      activeOpacity={0.8}>
      <View
        style={[
          styles.cardImg,
          {
            height: CARD_H,
            borderColor: isLive ? '#e50914' : 'transparent',
            borderWidth: isLive ? 2 : 0,
          },
        ]}>
        {item.thumbnail_url ? (
          <Image source={{uri: item.thumbnail_url}} style={styles.cardImgInner} />
        ) : (
          <View style={styles.noThumb}>
            <Text style={styles.thumbEmoji}>{isLive ? '📡' : '🎬'}</Text>
          </View>
        )}
        {item.isSeries && (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>סדרה</Text>
          </View>
        )}
        {isLive && (
          <View style={[styles.badge, styles.liveBadge]}>
            <Text style={styles.badgeText}>🔴 LIVE</Text>
          </View>
        )}
      </View>
      <Text style={styles.cardTitle} numberOfLines={2}>
        {item.name || item.title}
      </Text>
    </TouchableOpacity>
  );
}

// ── NetflixRow ────────────────────────────────────────────────────────────────

function NetflixRow({title, items, onPress, isLiveRow}) {
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
        renderItem={({item}) => <MovieCard item={item} onPress={onPress} />}
      />
    </View>
  );
}

// ── main component ────────────────────────────────────────────────────────────

export default function HomeScreen({navigation}) {
  const [movies, setMovies] = useState([]);
  const [liveChannels, setLiveChannels] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('הכל');
  const [showCategories, setShowCategories] = useState(false);
  const [detailItem, setDetailItem] = useState(null);
  const [showLogin, setShowLogin] = useState(false);
  const [user, setUser] = useState(null);
  const adminTapsRef = useRef(0);
  const adminTimerRef = useRef(null);

  // Load saved Google user
  useEffect(() => {
    AsyncStorage.getItem('zovex_google_user')
      .then(s => {
        if (s) setUser(JSON.parse(s));
      })
      .catch(() => {});
  }, []);

  const load = useCallback(async (refresh = false) => {
    if (refresh) {
      clearCache();
      setRefreshing(true);
    }
    const [data, live, hist] = await Promise.all([
      fetchMovies(),
      fetchLiveChannels(),
      fetchHistory(getUserId()),
    ]);
    setMovies(data);
    setLiveChannels(live);
    setHistory(hist);
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const seriesMap = useMemo(() => buildSeriesMap(movies), [movies]);

  const allCategories = useMemo(() => {
    const cats = [...new Set(movies.map(m => m.category).filter(Boolean))];
    const tabs = ['הכל'];
    if (liveChannels.length > 0) tabs.push('שידורים חיים');
    tabs.push(...cats);
    tabs.push('היסטוריה');
    return tabs;
  }, [movies, liveChannels]);

  const q = search.toLowerCase();

  const getItemsForCategory = useCallback(
    cat => {
      if (cat === 'שידורים חיים') {
        return liveChannels
          .filter(ch => (ch.title || ch.name || '').toLowerCase().includes(q))
          .map(ch => ({...ch, is_live: true, id: ch.id || ch.name}));
      }
      if (cat === 'היסטוריה') {
        return history
          .map(h => movies.find(m => m.id === h.media_id))
          .filter(Boolean);
      }
      const seen = {};
      const result = [];
      movies.forEach(m => {
        const matchQ =
          (m.title || '').toLowerCase().includes(q) ||
          (m.series_name || '').toLowerCase().includes(q);
        const matchC = cat === 'הכל' || m.category === cat;
        if (!matchQ || !matchC) return;
        if (m.series_name) {
          if (!seen[m.series_name]) {
            seen[m.series_name] = true;
            result.push({...seriesMap[m.series_name]});
          }
        } else {
          result.push({...m, isSeries: false});
        }
      });
      return result;
    },
    [movies, liveChannels, history, seriesMap, q],
  );

  const netflixRows = useMemo(() => {
    const rows = [];
    if (liveChannels.length > 0) {
      rows.push({
        title: 'שידורים חיים',
        isLiveRow: true,
        items: liveChannels.map(ch => ({
          ...ch,
          is_live: true,
          id: ch.id || ch.name,
        })),
      });
    }
    const historyItems = history
      .map(h => movies.find(m => m.id === h.media_id))
      .filter(Boolean);
    if (historyItems.length > 0) {
      rows.push({title: '▶ המשך צפייה', items: historyItems});
    }
    const cats = allCategories.filter(
      c => c !== 'הכל' && c !== 'שידורים חיים' && c !== 'היסטוריה',
    );
    cats.forEach(cat => {
      const items = getItemsForCategory(cat);
      if (items.length > 0) rows.push({title: cat, items});
    });
    return rows;
  }, [liveChannels, history, movies, allCategories, getItemsForCategory]);

  // Tap card → open detail modal (live channels go directly to player)
  const handleItemPress = useCallback(
    item => {
      if (item.is_live) {
        navigation.navigate('Player', {
          movie: {
            id: item.id,
            type: 'direct',
            video_url: item.video_url || item.url || '',
            title: item.title || item.name || 'שידור חי',
          },
        });
      } else {
        setDetailItem(item);
      }
    },
    [navigation],
  );

  // Play from detail modal
  const handlePlayDirect = useCallback(
    async item => {
      setDetailItem(null);
      if (item.is_live) {
        navigation.navigate('Player', {
          movie: {
            id: item.id,
            type: 'direct',
            video_url: item.video_url || item.url || '',
            title: item.title || item.name || 'שידור חי',
          },
        });
      } else {
        const startTime = await loadProgress(item.id, getUserId());
        navigation.navigate('Player', {movie: item, startTime: startTime || 0});
      }
    },
    [navigation],
  );

  // HeroBanner play → open detail modal
  const handleHeroPlay = useCallback(
    movie => {
      setDetailItem(
        movie.series_name
          ? {...seriesMap[movie.series_name], thumbnail_url: movie.thumbnail_url, description: movie.description}
          : movie,
      );
    },
    [seriesMap],
  );

  const handleHeroInfo = useCallback(
    movie => {
      setDetailItem(
        movie.series_name
          ? {...seriesMap[movie.series_name], thumbnail_url: movie.thumbnail_url, description: movie.description}
          : movie,
      );
    },
    [seriesMap],
  );

  // 5-tap ZOVEX title → admin
  const handleTitleTap = useCallback(() => {
    adminTapsRef.current += 1;
    clearTimeout(adminTimerRef.current);
    adminTimerRef.current = setTimeout(() => {
      adminTapsRef.current = 0;
    }, 2000);
    if (adminTapsRef.current >= 5) {
      adminTapsRef.current = 0;
      navigation.navigate('Admin');
    }
  }, [navigation]);

  const handleGoogleSuccess = useCallback(async userInfo => {
    setUser(userInfo);
    setShowLogin(false);
    try {
      await AsyncStorage.setItem(
        'zovex_google_user',
        JSON.stringify(userInfo),
      );
    } catch {}
  }, []);

  const handleSignOut = useCallback(async () => {
    setUser(null);
    try {
      await AsyncStorage.removeItem('zovex_google_user');
    } catch {}
  }, []);

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
      <TouchableOpacity onPress={handleTitleTap}>
        <Text style={styles.appTitle}>ZOVEX</Text>
      </TouchableOpacity>
      {user ? (
        <TouchableOpacity onPress={handleSignOut} style={styles.userBtn}>
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
        <TouchableOpacity
          onPress={() => setShowLogin(true)}
          style={styles.signInBtn}>
          <Text style={styles.signInTxt}>כניסה</Text>
        </TouchableOpacity>
      )}
    </View>
  );

  const SearchRow = (
    <View style={styles.searchRow}>
      <TextInput
        style={styles.search}
        placeholder="חיפוש סרט או סדרה..."
        placeholderTextColor="#555"
        value={search}
        onChangeText={v => {
          setSearch(v);
          if (!v) setCategory('הכל');
        }}
        textAlign="right"
      />
      <TouchableOpacity
        onPress={() => setShowCategories(s => !s)}
        style={[
          styles.catsToggleBtn,
          showCategories && styles.catsToggleBtnActive,
        ]}>
        <Text
          style={[
            styles.catsToggleTxt,
            showCategories && styles.catsToggleTxtActive,
          ]}>
          קטגוריות {showCategories ? '▲' : '▼'}
        </Text>
      </TouchableOpacity>
    </View>
  );

  const CategoriesBar = showCategories ? (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={styles.catsScroll}
      contentContainerStyle={styles.catsContent}>
      {allCategories.map(c => (
        <TouchableOpacity
          key={c}
          onPress={() => {
            setCategory(c);
            setShowCategories(false);
          }}
          style={[styles.catBtn, category === c && styles.catBtnActive]}>
          <Text
            style={[
              styles.catText,
              category === c && styles.catTextActive,
            ]}>
            {c}
          </Text>
        </TouchableOpacity>
      ))}
    </ScrollView>
  ) : null;

  return (
    <View style={styles.container}>
      {isNetflixMode ? (
        <ScrollView
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => load(true)}
              tintColor="#e50914"
            />
          }>
          {TopBar}
          <HeroBanner
            movies={movies}
            onPlay={handleHeroPlay}
            onInfo={handleHeroInfo}
          />
          {SearchRow}
          {CategoriesBar}
          {netflixRows.map(row => (
            <NetflixRow
              key={row.title}
              title={row.title}
              items={row.items}
              isLiveRow={row.isLiveRow}
              onPress={handleItemPress}
            />
          ))}
          {netflixRows.length === 0 && (
            <Text style={styles.empty}>אין תוכן זמין</Text>
          )}
        </ScrollView>
      ) : (
        <>
          {TopBar}
          {SearchRow}
          {CategoriesBar}
          <FlatList
            data={gridItems}
            keyExtractor={item => String(item.id)}
            numColumns={3}
            contentContainerStyle={styles.grid}
            refreshControl={
              <RefreshControl
                refreshing={refreshing}
                onRefresh={() => load(true)}
                tintColor="#e50914"
              />
            }
            renderItem={({item}) => (
              <MovieCard item={item} onPress={handleItemPress} />
            )}
            ListEmptyComponent={
              category === 'היסטוריה' ? (
                <View style={styles.historyEmpty}>
                  <Text style={styles.historyEmptyTitle}>
                    עדיין לא צפית בשום דבר
                  </Text>
                  <Text style={styles.historyEmptyDesc}>
                    ההיסטוריה שלך תופיע כאן
                  </Text>
                </View>
              ) : (
                <Text style={styles.empty}>לא נמצאו תוצאות</Text>
              )
            }
          />
        </>
      )}

      {/* Movie detail modal */}
      {detailItem && (
        <MovieDetailModal
          item={detailItem}
          allMovies={movies}
          onClose={() => setDetailItem(null)}
          onPlayDirect={handlePlayDirect}
        />
      )}

      {/* Google Sign-In modal */}
      <GoogleSignInModal
        visible={showLogin}
        onSuccess={handleGoogleSuccess}
        onClose={() => setShowLogin(false)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0a0a0a'},
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#0a0a0a',
  },
  loadingText: {color: '#aaa', marginTop: 12, fontSize: 14},

  // ── Top bar ──
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 8,
  },
  appTitle: {
    color: '#e50914',
    fontSize: 22,
    fontWeight: '900',
    letterSpacing: 6,
  },
  signInBtn: {
    backgroundColor: '#1a1a1a',
    borderWidth: 1,
    borderColor: '#333',
    borderRadius: 18,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  signInTxt: {color: '#fff', fontSize: 13, fontWeight: '700'},
  userBtn: {padding: 2},
  userAvatar: {width: 34, height: 34, borderRadius: 17},
  userAvatarFallback: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: '#e50914',
    justifyContent: 'center',
    alignItems: 'center',
  },

  // ── HeroBanner ──
  hero: {width: '100%', height: 360},
  heroBg: {width: '100%', height: 360, justifyContent: 'flex-end'},
  heroGradient: {...StyleSheet.absoluteFillObject, backgroundColor: 'transparent'},
  heroContent: {padding: 16, paddingBottom: 36},
  heroTitle: {
    color: '#fff',
    fontSize: 26,
    fontWeight: '900',
    textAlign: 'right',
    textShadowColor: 'rgba(0,0,0,0.8)',
    textShadowOffset: {width: 0, height: 2},
    textShadowRadius: 8,
    marginBottom: 6,
  },
  heroDesc: {
    color: 'rgba(255,255,255,0.82)',
    fontSize: 13,
    textAlign: 'right',
    lineHeight: 20,
    marginBottom: 14,
    textShadowColor: 'rgba(0,0,0,0.6)',
    textShadowOffset: {width: 0, height: 1},
    textShadowRadius: 4,
  },
  heroBtns: {flexDirection: 'row', justifyContent: 'flex-end', gap: 10},
  heroBtnPlay: {
    backgroundColor: '#fff',
    paddingVertical: 10,
    paddingHorizontal: 22,
    borderRadius: 8,
  },
  heroBtnPlayText: {color: '#000', fontSize: 15, fontWeight: '800'},
  heroBtnInfo: {
    backgroundColor: 'rgba(100,100,110,0.55)',
    paddingVertical: 10,
    paddingHorizontal: 18,
    borderRadius: 8,
  },
  heroBtnInfoText: {color: '#fff', fontSize: 15, fontWeight: '700'},
  heroDots: {
    position: 'absolute',
    bottom: 8,
    left: 0,
    right: 0,
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 5,
  },
  heroDot: {width: 6, height: 6, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.35)'},
  heroDotActive: {backgroundColor: '#fff', width: 18},

  // ── Search + Categories ──
  searchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 6,
    gap: 8,
  },
  search: {
    flex: 1,
    backgroundColor: '#1a1a1a',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: '#fff',
    fontSize: 14,
    borderWidth: 1,
    borderColor: '#333',
  },
  catsToggleBtn: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 10,
    backgroundColor: '#1a1a1a',
    borderWidth: 1,
    borderColor: '#333',
  },
  catsToggleBtnActive: {backgroundColor: '#e50914', borderColor: '#e50914'},
  catsToggleTxt: {color: '#aaa', fontSize: 13, fontWeight: '600'},
  catsToggleTxtActive: {color: '#fff'},

  catsScroll: {flexGrow: 0, marginBottom: 6},
  catsContent: {paddingHorizontal: 8, paddingVertical: 4},
  catBtn: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    marginHorizontal: 4,
    borderRadius: 20,
    backgroundColor: '#1a1a1a',
    borderWidth: 1,
    borderColor: '#333',
  },
  catBtnActive: {backgroundColor: '#e50914', borderColor: '#e50914'},
  catText: {color: '#aaa', fontSize: 13, fontWeight: '600'},
  catTextActive: {color: '#fff'},

  // ── Netflix rows ──
  rowWrap: {marginBottom: 24},
  rowHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    marginBottom: 10,
    justifyContent: 'flex-end',
  },
  liveIcon: {color: '#e50914', fontSize: 10, marginLeft: 6},
  rowTitle: {color: '#fff', fontSize: 16, fontWeight: '800', textAlign: 'right'},
  rowList: {paddingHorizontal: 10},

  // ── Card ──
  card: {marginHorizontal: 5, borderRadius: 10, overflow: 'hidden'},
  cardImg: {
    width: '100%',
    borderRadius: 10,
    overflow: 'hidden',
    backgroundColor: '#1c1c1e',
  },
  cardImgInner: {width: '100%', height: '100%', resizeMode: 'cover'},
  noThumb: {
    width: '100%',
    height: '100%',
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#1c1c1e',
  },
  thumbEmoji: {fontSize: 28},
  cardTitle: {
    color: '#f2f2f2',
    fontSize: 11,
    fontWeight: '700',
    paddingTop: 5,
    paddingHorizontal: 2,
    textAlign: 'right',
  },
  badge: {
    position: 'absolute',
    top: 7,
    right: 7,
    backgroundColor: 'rgba(0,0,0,0.65)',
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  liveBadge: {backgroundColor: '#e50914'},
  badgeText: {color: '#fff', fontSize: 9, fontWeight: '800'},

  // ── Grid mode ──
  grid: {paddingHorizontal: 8, paddingBottom: 20, paddingTop: 4},

  empty: {color: '#555', textAlign: 'center', marginTop: 60, fontSize: 16},
  historyEmpty: {alignItems: 'center', marginTop: 80, paddingHorizontal: 30},
  historyEmptyTitle: {
    color: '#aaa',
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 8,
  },
  historyEmptyDesc: {color: '#555', fontSize: 13, textAlign: 'center'},
});
