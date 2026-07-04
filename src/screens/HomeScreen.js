import React, {useEffect, useState, useMemo, useCallback} from 'react';
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
} from 'react-native';
import {
  fetchMovies,
  fetchLiveChannels,
  fetchHistory,
  clearCache,
} from '../api/movies';
import {getUserId} from '../api/userStore';

const {width: SW} = Dimensions.get('window');
const CARD_W = SW * 0.34;
const CARD_H = CARD_W * 1.45;

// ── helpers ────────────────────────────────────────────────────────────────

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

// ── sub-components ─────────────────────────────────────────────────────────

function MovieCard({item, onPress}) {
  return (
    <TouchableOpacity
      style={[styles.card, {width: CARD_W}]}
      onPress={() => onPress(item)}
      activeOpacity={0.8}>
      {item.thumbnail_url ? (
        <Image
          source={{uri: item.thumbnail_url}}
          style={[styles.cardImg, {height: CARD_H}]}
        />
      ) : (
        <View style={[styles.cardImg, {height: CARD_H}, styles.noThumb]}>
          <Text style={styles.thumbEmoji}>{item.is_live ? '📡' : '🎬'}</Text>
        </View>
      )}
      <Text style={styles.cardTitle} numberOfLines={2}>
        {item.name || item.title}
      </Text>
      {item.isSeries && (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>סדרה</Text>
        </View>
      )}
      {item.is_live && (
        <View style={[styles.badge, styles.liveBadge]}>
          <Text style={styles.badgeText}>🔴 LIVE</Text>
        </View>
      )}
    </TouchableOpacity>
  );
}

function NetflixRow({title, items, onPress}) {
  if (!items || items.length === 0) return null;
  return (
    <View style={styles.rowWrap}>
      <Text style={styles.rowTitle}>{title}</Text>
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

// ── main component ─────────────────────────────────────────────────────────

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

  // Netflix rows for "הכל" mode
  const netflixRows = useMemo(() => {
    const rows = [];
    if (liveChannels.length > 0) {
      rows.push({
        title: '👁️ שידורים חיים',
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
      rows.push({title: '▶️ המשך צפייה', items: historyItems});
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
      } else if (item.isSeries) {
        navigation.navigate('Series', {
          seriesName: item.series_name || item.name,
          movies,
        });
      } else {
        navigation.navigate('Player', {movie: item});
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
      <TextInput
        style={styles.search}
        placeholder="חיפוש סרט או סדרה..."
        placeholderTextColor="#555"
        value={search}
        onChangeText={v => {
          setSearch(v);
          if (v && category === 'הכל') setCategory('הכל');
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
            <Text style={[styles.catText, category === c && styles.catTextActive]}>
              {c}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

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
          {netflixRows.map(row => (
            <NetflixRow
              key={row.title}
              title={row.title}
              items={row.items}
              onPress={handleItemPress}
            />
          ))}
          {netflixRows.length === 0 && (
            <Text style={styles.empty}>אין תוכן זמין</Text>
          )}
        </ScrollView>
      ) : (
        <FlatList
          data={gridItems}
          keyExtractor={item => String(item.id)}
          numColumns={2}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => load(true)}
              tintColor="#e50914"
            />
          }
          renderItem={({item}) => (
            <TouchableOpacity
              style={[styles.gridCard, {width: (SW - 36) / 2}]}
              activeOpacity={0.8}
              onPress={() => handleItemPress(item)}>
              {item.thumbnail_url ? (
                <Image source={{uri: item.thumbnail_url}} style={styles.thumb} />
              ) : (
                <View style={[styles.thumb, styles.noThumb]}>
                  <Text style={styles.thumbEmoji}>
                    {item.is_live ? '📡' : '🎬'}
                  </Text>
                </View>
              )}
              <Text style={styles.cardTitle} numberOfLines={2}>
                {item.name || item.title}
              </Text>
              {item.isSeries && (
                <View style={styles.badge}>
                  <Text style={styles.badgeText}>סדרה</Text>
                </View>
              )}
              {item.is_live && (
                <View style={[styles.badge, styles.liveBadge]}>
                  <Text style={styles.badgeText}>🔴 LIVE</Text>
                </View>
              )}
            </TouchableOpacity>
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

  search: {
    margin: 12,
    marginBottom: 8,
    backgroundColor: '#1a1a1a',
    borderRadius: 10,
    padding: 12,
    color: '#fff',
    fontSize: 15,
    borderWidth: 1,
    borderColor: '#333',
  },
  catsScroll: {flexGrow: 0, marginBottom: 6},
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

  // Netflix rows
  rowWrap: {marginBottom: 20},
  rowTitle: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '700',
    paddingHorizontal: 14,
    marginBottom: 8,
    textAlign: 'right',
  },
  rowList: {paddingHorizontal: 10},
  card: {marginHorizontal: 5, borderRadius: 10, overflow: 'hidden', backgroundColor: '#1a1a1a'},
  cardImg: {width: '100%', resizeMode: 'cover'},
  cardTitle: {
    color: '#fff',
    fontSize: 11,
    fontWeight: '600',
    padding: 6,
    textAlign: 'right',
  },

  // Grid
  list: {paddingHorizontal: 8, paddingBottom: 20, paddingTop: 4},
  gridCard: {
    margin: 6,
    borderRadius: 12,
    overflow: 'hidden',
    backgroundColor: '#1a1a1a',
  },
  thumb: {width: '100%', aspectRatio: 2 / 3, resizeMode: 'cover'},
  noThumb: {
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#222',
  },
  thumbEmoji: {fontSize: 28},

  badge: {
    position: 'absolute',
    top: 7,
    left: 7,
    backgroundColor: '#e50914',
    borderRadius: 5,
    paddingHorizontal: 5,
    paddingVertical: 2,
  },
  liveBadge: {backgroundColor: '#cc0000'},
  badgeText: {color: '#fff', fontSize: 9, fontWeight: '800'},

  empty: {color: '#555', textAlign: 'center', marginTop: 60, fontSize: 16},
  historyEmpty: {
    alignItems: 'center',
    marginTop: 80,
    paddingHorizontal: 30,
  },
  historyEmptyTitle: {color: '#aaa', fontSize: 18, fontWeight: '600', marginBottom: 8},
  historyEmptyDesc: {color: '#555', fontSize: 13, textAlign: 'center'},
});
