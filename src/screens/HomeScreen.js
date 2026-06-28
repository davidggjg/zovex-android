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
} from 'react-native';
import {fetchMovies, clearCache} from '../api/movies';

const CATEGORIES = ['הכל', 'סדרות ישראליות', 'סדרות', 'סרטים', 'סדרות ילדים', 'מצוירים', 'אימה'];

export default function HomeScreen({navigation}) {
  const [movies, setMovies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('הכל');

  const load = useCallback(async (refresh = false) => {
    if (refresh) {
      clearCache();
      setRefreshing(true);
    }
    const data = await fetchMovies();
    setMovies(data);
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const items = useMemo(() => {
    const q = search.toLowerCase();
    const seenSeries = {};
    const result = [];

    movies.forEach(m => {
      const matchCat = category === 'הכל' || m.category === category;
      const matchQ =
        (m.title || '').toLowerCase().includes(q) ||
        (m.series_name || '').toLowerCase().includes(q);
      if (!matchCat || !matchQ) return;

      if (m.series_name) {
        if (!seenSeries[m.series_name]) {
          seenSeries[m.series_name] = true;
          result.push({
            id: 'series_' + m.series_name,
            isSeries: true,
            name: m.series_name,
            thumbnail_url: m.thumbnail_url,
            category: m.category,
          });
        }
      } else {
        result.push({...m, isSeries: false});
      }
    });

    return result;
  }, [movies, search, category]);

  const renderItem = ({item}) => (
    <TouchableOpacity
      style={styles.card}
      activeOpacity={0.8}
      onPress={() => {
        if (item.isSeries) {
          navigation.navigate('Series', {
            seriesName: item.name,
            movies,
          });
        } else {
          navigation.navigate('Player', {movie: item});
        }
      }}>
      {item.thumbnail_url ? (
        <Image source={{uri: item.thumbnail_url}} style={styles.thumb} />
      ) : (
        <View style={[styles.thumb, styles.noThumb]}>
          <Text style={{fontSize: 32}}>🎬</Text>
        </View>
      )}
      <Text style={styles.cardTitle} numberOfLines={2}>
        {item.isSeries ? item.name : item.title}
      </Text>
      {item.isSeries && (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>סדרה</Text>
        </View>
      )}
    </TouchableOpacity>
  );

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#e50914" />
        <Text style={styles.loadingText}>טוען...</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.search}
        placeholder="חיפוש סרט או סדרה..."
        placeholderTextColor="#555"
        value={search}
        onChangeText={setSearch}
        textAlign="right"
      />

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.catsScroll}>
        {CATEGORIES.map(c => (
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

      <FlatList
        data={items}
        keyExtractor={item => item.id}
        renderItem={renderItem}
        numColumns={2}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => load(true)}
            tintColor="#e50914"
          />
        }
        ListEmptyComponent={
          <Text style={styles.empty}>לא נמצאו תוצאות</Text>
        }
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
  search: {
    margin: 12,
    backgroundColor: '#1a1a1a',
    borderRadius: 10,
    padding: 12,
    color: '#fff',
    fontSize: 15,
    borderWidth: 1,
    borderColor: '#333',
  },
  catsScroll: {paddingHorizontal: 8, marginBottom: 8, flexGrow: 0},
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
  list: {paddingHorizontal: 8, paddingBottom: 20},
  card: {
    flex: 1,
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
  cardTitle: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '600',
    padding: 8,
    textAlign: 'right',
  },
  badge: {
    position: 'absolute',
    top: 8,
    left: 8,
    backgroundColor: '#e50914',
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  badgeText: {color: '#fff', fontSize: 10, fontWeight: '700'},
  empty: {
    color: '#555',
    textAlign: 'center',
    marginTop: 60,
    fontSize: 16,
  },
});
