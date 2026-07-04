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
} from 'react-native';
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

// ── HeroBanner ──────────────────────────────────────────────────────────────

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
            <Text style={styles.heroTitle}>{movie.series_name || movie.title}</Text>
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

// ── helpers ─────────────────────────────────────────────────────────────────

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
        category: m.category,
        episodes: [],
      };
    }
    map[m.series_name].episodes.push(m);
  });
  return map;
}

// ── MovieCard ────────────────────────────────────────────────────────────────

function MovieCard({item, onPress}) {
  const isLive = !!item.is_live;
  return (
    <TouchableOpacity
      style={[styles.card, {width: CARD_W}]}
      onPress={() => onPress(item)}
      activeOpacity={0.8}>
      <View style={[styles.cardImg, {height: CARD_H, borderColor: isLive ? '#e50914' : 'transparent', borderWidth: isLive ? 2 : 0}]}>
        {item.thumbnail_url ? (
          <Image
            source={{uri: item.thumbnail_url}}
            style={styles.cardImgInner}
          />
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

// ── NetflixRow ───────────────────────────────────────────────────────────────

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

// ── main component ───────────────────────────────────────────────────────────

export default function HomeScreen({navigation}) {
  const [movies, setMovies] = useState([]);
  const [liveChannels, setLiveChannels] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('הכל');

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

  const handleItemPress = useCallback(
    async item => {
      if (item.is_live) {
        navigation.navigate('Player', {
          movie: {
            id: item.id,
            type: 'direct',
            video_url: item.video_url || item.url || '',
            title: item.title || item.name || 'שידור חי',
          },
        });
      } else if (item.isSeries) {
        navigation.navigate('Series', {
          seriesName: item.series_name || item.name,
          movies,
        });
      } else {
        const startTime = await loadProgress(item.id, getUserId());
        navigation.navigate('Player', {movie: item, startTime: startTime || 0});
      }
    },
    [navigation, movies],
  );

  const handleHeroPlay = useCallback(
    async movie => {
      if (movie.series_name) {
        navigation.navigate('Series', {
          seriesName: movie.series_name,
          movies,
        });
      } else {
        const startTime = await loadProgress(movie.id, getUserId());
        navigation.navigate('Player', {movie, startTime: startTime || 0});
      }
    },
    [navigation, movies],
  );

  const handleHeroInfo = useCallback(
    movie => {
      if (movie.series_name) {
        navigation.navigate('Series', {
          seriesName: movie.series_name,
          movies,
        });
      } else {
        navigation.navigate('Series', {
          seriesName: movie.title,
          movies: [movie],
        });
      }
    },
    [navigation, movies],
  );

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
          <HeroBanner
            movies={movies}
            onPlay={handleHeroPlay}
            onInfo={handleHeroInfo}
          />

          {/* Search + category tabs */}
          <View style={styles.searchWrap}>
            <TextInput
              style={styles.search}
              placeholder="חיפוש סרט או סדרה..."
              placeholderTextColor="#555"
              value={search}
              onChangeText={v => setSearch(v)}
              textAlign="right"
            />
          </View>

          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={styles.catsScroll}
            contentContainerStyle={styles.catsContent}>
            {allCategories.map(c => (
              <TouchableOpacity
                key={c}
                onPress={() => setCategory(c)}
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
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={styles.catsScroll}
            contentContainerStyle={styles.catsContent}>
            {allCategories.map(c => (
              <TouchableOpacity
                key={c}
                onPress={() => setCategory(c)}
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

  // ── HeroBanner ──
  hero: {width: '100%', height: 400},
  heroBg: {width: '100%', height: 400, justifyContent: 'flex-end'},
  heroGradient: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'transparent',
    // Linear gradient via overlapping Views
  },
  heroContent: {
    padding: 16,
    paddingBottom: 40,
    background: 'transparent',
  },
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
  heroBtns: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 10,
  },
  heroBtnPlay: {
    backgroundColor: '#fff',
    paddingVertical: 10,
    paddingHorizontal: 22,
    borderRadius: 8,
  },
  heroBtnPlayText: {
    color: '#000',
    fontSize: 15,
    fontWeight: '800',
  },
  heroBtnInfo: {
    backgroundColor: 'rgba(100,100,110,0.55)',
    paddingVertical: 10,
    paddingHorizontal: 18,
    borderRadius: 8,
  },
  heroBtnInfoText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '700',
  },
  heroDots: {
    position: 'absolute',
    bottom: 8,
    left: 0,
    right: 0,
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 5,
  },
  heroDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: 'rgba(255,255,255,0.35)',
  },
  heroDotActive: {
    backgroundColor: '#fff',
    width: 18,
  },

  // ── Search + Cats ──
  searchWrap: {paddingHorizontal: 12, paddingTop: 12, paddingBottom: 6},
  search: {
    marginHorizontal: 12,
    marginVertical: 8,
    backgroundColor: '#1a1a1a',
    borderRadius: 10,
    padding: 12,
    color: '#fff',
    fontSize: 15,
    borderWidth: 1,
    borderColor: '#333',
  },
  catsScroll: {flexGrow: 0, marginBottom: 8},
  catsContent: {paddingHorizontal: 8},
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
  liveIcon: {
    color: '#e50914',
    fontSize: 10,
    marginLeft: 6,
    marginRight: 0,
  },
  rowTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '800',
    textAlign: 'right',
  },
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
