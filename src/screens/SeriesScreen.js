import React, {useMemo, useState, useCallback} from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  Image,
  ScrollView,
} from 'react-native';

import {loadProgress} from '../api/movies';
import {getUserId} from '../api/userStore';

export default function SeriesScreen({route, navigation}) {
  const {seriesName, movies} = route.params;
  const [selectedSeason, setSelectedSeason] = useState(1);

  const openEpisode = useCallback(async item => {
    const startTime = await loadProgress(item.id, getUserId());
    navigation.navigate('Player', {movie: item, startTime: startTime || 0});
  }, [navigation]);

  const episodes = useMemo(
    () => movies.filter(m => m.series_name === seriesName),
    [movies, seriesName],
  );

  const seasons = useMemo(() => {
    const s = [
      ...new Set(episodes.map(e => e.season_number || 1)),
    ].sort((a, b) => a - b);
    return s;
  }, [episodes]);

  const filtered = useMemo(
    () =>
      episodes
        .filter(e => (e.season_number || 1) === selectedSeason)
        .sort((a, b) => (a.episode_number || 0) - (b.episode_number || 0)),
    [episodes, selectedSeason],
  );

  const poster = episodes[0]?.thumbnail_url;
  const desc = episodes[0]?.description;

  return (
    <View style={styles.container}>
      <FlatList
        data={filtered}
        keyExtractor={item => item.id}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          <>
            <View style={styles.header}>
              {poster && (
                <Image source={{uri: poster}} style={styles.poster} />
              )}
              <View style={styles.headerInfo}>
                <Text style={styles.seriesTitle}>{seriesName}</Text>
                <Text style={styles.epCount}>{episodes.length} פרקים</Text>
                {desc ? (
                  <Text style={styles.desc} numberOfLines={3}>
                    {desc}
                  </Text>
                ) : null}
              </View>
            </View>

            {seasons.length > 1 && (
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                style={styles.seasonsRow}>
                {seasons.map(s => (
                  <TouchableOpacity
                    key={s}
                    onPress={() => setSelectedSeason(s)}
                    style={[
                      styles.seasonBtn,
                      selectedSeason === s && styles.seasonBtnActive,
                    ]}>
                    <Text
                      style={[
                        styles.seasonText,
                        selectedSeason === s && styles.seasonTextActive,
                      ]}>
                      עונה {s}
                    </Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
            )}
          </>
        }
        renderItem={({item}) => (
          <TouchableOpacity
            style={styles.epRow}
            activeOpacity={0.7}
            onPress={() => openEpisode(item)}>
            {item.thumbnail_url ? (
              <Image
                source={{uri: item.thumbnail_url}}
                style={styles.epThumb}
              />
            ) : (
              <View style={[styles.epThumb, styles.noThumb]}>
                <Text style={{fontSize: 22}}>▶️</Text>
              </View>
            )}
            <View style={styles.epInfo}>
              <Text style={styles.epNum}>פרק {item.episode_number}</Text>
              <Text style={styles.epTitle} numberOfLines={2}>
                {item.episode_title || item.title}
              </Text>
            </View>
          </TouchableOpacity>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0a0a0a'},
  header: {flexDirection: 'row', padding: 16, alignItems: 'flex-start'},
  poster: {width: 80, height: 115, borderRadius: 10, resizeMode: 'cover'},
  headerInfo: {flex: 1, marginRight: 14},
  seriesTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '800',
    textAlign: 'right',
  },
  epCount: {color: '#aaa', fontSize: 13, marginTop: 4, textAlign: 'right'},
  desc: {
    color: '#888',
    fontSize: 12,
    marginTop: 6,
    lineHeight: 18,
    textAlign: 'right',
  },
  seasonsRow: {
    paddingHorizontal: 12,
    marginBottom: 8,
    flexGrow: 0,
  },
  seasonBtn: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    marginHorizontal: 4,
    borderRadius: 20,
    backgroundColor: '#1a1a1a',
    borderWidth: 1,
    borderColor: '#333',
  },
  seasonBtnActive: {backgroundColor: '#e50914', borderColor: '#e50914'},
  seasonText: {color: '#aaa', fontWeight: '600'},
  seasonTextActive: {color: '#fff'},
  list: {paddingBottom: 30},
  epRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1a1a1a',
  },
  epThumb: {width: 130, height: 73, borderRadius: 8, resizeMode: 'cover'},
  noThumb: {
    backgroundColor: '#222',
    justifyContent: 'center',
    alignItems: 'center',
  },
  epInfo: {flex: 1, marginRight: 12},
  epNum: {
    color: '#e50914',
    fontSize: 12,
    fontWeight: '700',
    textAlign: 'right',
  },
  epTitle: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
    marginTop: 4,
    textAlign: 'right',
  },
});
