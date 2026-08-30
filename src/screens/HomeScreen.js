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
  Platform,
  BackHandler,
  Share,
} from 'react-native';
import {GoogleSignin} from '@react-native-google-signin/google-signin';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  fetchMovies,
  fetchMoviesFast,
  fetchItemDetail,
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
import {useIsFocused} from '@react-navigation/native';
import TvFocusable from '../components/TvFocusable';
import LiveChannelModal from '../components/LiveChannelModal';
import AdBanner from '../components/AdBanner';
import SupportModal from '../components/SupportModal';
import UpdateDialog from '../components/UpdateDialog';
import {DISCORD_URL, TELEGRAM_URL} from '../config/links';

const DOWNLOADS_CATEGORY = 'ההורדות שלי';

// בטלוויזיה מודדים לפי המסך ולא לפי החלון: החלון עלול להימסר קטן יותר
// (למשל אחרי חזרה מהנגן), וזה מה שהפך את הרשת ל"מסך של טלפון". המסך תמיד
// מדווח את הרוחב המלא של הטלוויזיה.
const {width: SW, height: SH} = Dimensions.get(Platform.isTV ? 'screen' : 'window');
// בטלוויזיה המסך רחב וברירת המחדל של 3 עמודות ייצרה אריחים ענקיים שקשה
// לנווט ביניהם. בטלוויזיה עוברים ל-6 עמודות (אריחים קטנים כמו בטלפון,
// מותאמים למרחק צפייה) ובטלפון נשארים 3.
const MAIN_SITE = 'https://zovex.duckdns.org';
const IS_TV = Platform.isTV;
const NUM_COLS = IS_TV ? 6 : 3;
// לכל אריח 5px שוליים מכל צד (10) + לרשת 8px ריפוד מכל צד (16):
// SW = N*CARD_W + N*10 + 16  →  CARD_W = (SW - 16 - N*10) / N
const CARD_W = Math.floor((SW - 16 - NUM_COLS * 10) / NUM_COLS);
const CARD_H = Math.floor(CARD_W * 1.48);
// באנר הראשי. בטלפון הפוסטרים לאורך (2:3), ולכן הגובה נגזר מהרוחב. בטלוויזיה
// אותה נוסחה נתנה 1.25 × 1920 = 2400 פיקסלים על מסך שגובהו 1080 — באנר גבוה
// פי שניים מהמסך, וזה מה שחרג. כאן הוא נחסם מול *גובה* המסך: בטלוויזיה 58%,
// כך שנשארת הצצה לשורת האריחים הראשונה מתחתיו, ובטלפון תקרה של 70% כדי שגם
// מסכים צרים לא יאבדו את שאר הדף.
const HERO_H = IS_TV
  ? Math.round(SH * 0.58)
  : Math.min(Math.round(SW * 1.25), Math.round(SH * 0.7));

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
      <TvFocusable
        style={[mdStyles.dlBtn, mdStyles.dlBtnDone, compact && mdStyles.dlBtnCompact]}
        activeOpacity={0.8}
        onPress={() => onDeleteDownload(id)}>
        <Text style={[mdStyles.dlBtnTxt, mdStyles.dlBtnDoneTxt]}>{compact ? '✓' : '✓ הורד · הסר'}</Text>
      </TvFocusable>
    );
  }
  return (
    <TvFocusable
      style={[mdStyles.dlBtn, compact && mdStyles.dlBtnCompact]}
      activeOpacity={0.8}
      onPress={() => onDownload(item)}>
      <Text style={mdStyles.dlBtnTxt}>{compact ? '⬇' : '⬇ הורדה'}</Text>
    </TvFocusable>
  );
}

function MovieDetailModal({
  item, allMovies, onClose, onPlayDirect,
  downloadedIds, downloadingId, downloadProgress, onDownload, onDeleteDownload,
}) {
  const [selectedSeason, setSelectedSeason] = useState(null);
  const [showSeasonPicker, setShowSeasonPicker] = useState(false);
  const [seasonLoading, setSeasonLoading] = useState(false);
  // ה-description לא נשלח ב-/content/lite (זה השדה הכבד). כשפותחים סרט
  // מושכים אותו לפי דרישה מ-/content/item/{id}. אם הפריט כבר מכיל description
  // (למשל מ-cache ישן) — משתמשים בו כמו שהוא.
  const [fetchedDesc, setFetchedDesc] = useState(null);
  useEffect(() => {
    setFetchedDesc(null);
    if (!item || item.description) return;
    // לסדרה הפריט הוא פסאודו (id "series_..." בלי description); מושכים את
    // התיאור מהפרק הראשון האמיתי. לסרט — לפי ה-id של הפריט עצמו.
    let detailId = item.id;
    if (item.series_name) {
      const first = allMovies.find(m => m.series_name === item.series_name && m.id);
      if (first) detailId = first.id;
    }
    if (!detailId || String(detailId).startsWith('series_')) return;
    let alive = true;
    fetchItemDetail(detailId).then(full => {
      if (alive && full && full.description) setFetchedDesc(full.description);
    });
    return () => { alive = false; };
  }, [item, allMovies]);
  const description = item?.description || fetchedDesc || '';

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
    // ההשהיה כאן הייתה כדי להספיק להראות ספינר, אבל היא נוספה לכל החלפת
    // עונה — ובשלט זה מרגיש כמו אפליקציה תקועה. הרשימה מתחלפת מיד.
    setSelectedSeason(s);
    setSeasonLoading(false);
  }, [activeSeason]);

  const displayTitle = item ? (item.series_name || item.title || item.name || '') : '';

  // קישור לשיתוף. ה-slug הוא מה שהאתר משתמש בו (‎/<slug>/watch); בלעדיו
  // נופלים לקישור לפי מזהה, שגם הוא נפתח באתר.
  //
  // חייב להיות *לפני* ה-return המוקדם: קודם הוא ישב אחריו, כלומר מספר
  // ה-hooks השתנה בין רינדור עם פריט לרינדור בלעדיו — הפרה של כללי ה-hooks
  // שמבלבלת את React ומייצרת התנהגות לא צפויה בדיוק במסך הזה.
  const onShare = useCallback(() => {
    if (!item) return;
    const base = item.custom_slug
      ? `${MAIN_SITE}/${item.custom_slug}/watch`
      : `${MAIN_SITE}/watch?id=${encodeURIComponent(item.id || '')}`;
    Share.share({message: `${displayTitle}\n${base}`}).catch(() => {});
  }, [item, displayTitle]);

  if (!item) return null;
  const firstEp = visibleEpisodes.length > 0 ? visibleEpisodes[0] : null;

  return (
    // Modal אמיתי ולא View: כשזה היה שכבה רגילה, הכרטיסים שמאחור נשארו
    // focusable — ה-focus בשלט נשאר על הכרטיס, ולחיצה על OK הפעילה שוב את
    // פתיחת הפריט (תרומה → פרטים → תרומה...) במקום לנגן. Modal מוציא את
    // הרקע ממסלול ה-focus, וגם נותן טיפול נכון בכפתור "חזור".
    <Modal transparent animationType="fade" visible onRequestClose={onClose}>
    <View style={mdStyles.overlay}>
      {/* רקע לסגירה בלחיצה — נשאר Touchable כדי שלא ייתפס כיעד focus בשלט */}
      <TouchableOpacity style={StyleSheet.absoluteFillObject} onPress={onClose} activeOpacity={1} />
      <View style={mdStyles.sheet}>
        <TvFocusable style={mdStyles.closeBtn} onPress={onClose}>
          <Text style={mdStyles.closeTxt}>✕</Text>
        </TvFocusable>
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
            {!!description && (
              <Text style={mdStyles.desc} numberOfLines={5}>{description}</Text>
            )}
            <View style={mdStyles.actionsRow}>
              <TvFocusable style={mdStyles.playBtn} activeOpacity={0.8}
                hasFocus={IS_TV}
                onPress={() => onPlayDirect(firstEp || item)}>
                <Text style={mdStyles.playTxt}>▶ הפעל</Text>
              </TvFocusable>
              <DownloadControl
                item={firstEp || item}
                downloadedIds={downloadedIds}
                downloadingId={downloadingId}
                downloadProgress={downloadProgress}
                onDownload={onDownload}
                onDeleteDownload={onDeleteDownload}
              />
              {/* שיתוף — מוסתר בטלוויזיה: אין שם למי לשתף ואין מקלדת, והכפתור
                  רק גוזל תחנה בניווט עם השלט. */}
              {!IS_TV && (
                <TvFocusable style={mdStyles.shareBtn} activeOpacity={0.8} onPress={onShare}>
                  <Text style={mdStyles.shareTxt}>שתף</Text>
                </TvFocusable>
              )}
            </View>
          </View>
          {episodes.length > 1 && (
            <View style={mdStyles.epsSection}>
              {seasons.length > 1 && (
                <View style={mdStyles.seasonRow}>
                  <TvFocusable style={mdStyles.seasonBtn} onPress={() => setShowSeasonPicker(true)} activeOpacity={0.8}>
                    <Text style={mdStyles.seasonBtnTxt}>עונה {activeSeason} ▾</Text>
                  </TvFocusable>
                </View>
              )}
              <Text style={mdStyles.epsHeader}>פרקים ({visibleEpisodes.length})</Text>
              {seasonLoading ? (
                <View style={{alignItems: 'center', paddingVertical: 30}}>
                  <ActivityIndicator size="large" color="#e50914" />
                </View>
              ) : (
                visibleEpisodes.map(ep => (
                  <TvFocusable key={ep.id} style={mdStyles.epRow} activeOpacity={0.75} onPress={() => onPlayDirect(ep)}>
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
                  </TvFocusable>
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
                <TvFocusable key={s} style={[mdStyles.seasonPickerItem, s === activeSeason && mdStyles.seasonPickerItemActive]} onPress={() => handleSeasonSelect(s)}>
                  <Text style={[mdStyles.seasonPickerTxt, s === activeSeason && mdStyles.seasonPickerTxtActive]}>עונה {s}</Text>
                </TvFocusable>
              ))}
            </View>
          </TouchableOpacity>
        </Modal>
      )}
    </View>
    </Modal>
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
  shareBtn: {
    backgroundColor: '#1f1f1f', borderRadius: 12, paddingVertical: 14,
    paddingHorizontal: 18, alignItems: 'center', justifyContent: 'center',
  },
  shareTxt: {color: '#fff', fontSize: 15, fontWeight: '700'},
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

// פוטר קבוע בתחתית מסך הבית — מקביל לפוטר שבאתר. גלוי גם לאורחים (שאין להם
// תפריט משתמש), כדי שהתנאים והמדיניות יהיו נגישים לכולם, לא רק למחוברים.
function HomeFooter({navigation}) {
  const link = doc => () => navigation.navigate('Legal', {doc});
  const open = url => () => Linking.openURL(url).catch(() => {});
  return (
    <View style={ftStyles.wrap}>
      <View style={ftStyles.row}>
        <TvFocusable onPress={link('about')}><Text style={ftStyles.link}>אודות</Text></TvFocusable>
        <TvFocusable onPress={link('terms')}><Text style={ftStyles.link}>תנאי שימוש</Text></TvFocusable>
        <TvFocusable onPress={link('privacy')}><Text style={ftStyles.link}>פרטיות</Text></TvFocusable>
        <TvFocusable onPress={link('copyright')}><Text style={ftStyles.link}>זכויות יוצרים</Text></TvFocusable>
      </View>
      <View style={ftStyles.row}>
        <TvFocusable onPress={open(DISCORD_URL)}><Text style={[ftStyles.link, {color: '#7c85f5'}]}>דיסקורד</Text></TvFocusable>
        <TvFocusable onPress={open(TELEGRAM_URL)}><Text style={[ftStyles.link, {color: '#5b9bd5'}]}>טלגרם</Text></TvFocusable>
      </View>
      <Text style={ftStyles.note}>ZOVEX · שירות חינמי, ללא מטרות רווח</Text>
    </View>
  );
}

const ftStyles = StyleSheet.create({
  wrap: {borderTopWidth: 1, borderTopColor: '#1c1c1c', marginTop: 20, paddingTop: 18, paddingBottom: 30, paddingHorizontal: 16},
  row: {flexDirection: 'row-reverse', flexWrap: 'wrap', justifyContent: 'center', gap: 16, marginBottom: 10},
  link: {color: '#888', fontSize: 13},
  note: {color: '#555', fontSize: 11, textAlign: 'center', marginTop: 4},
});

// memo: הבאנר מחזיק טיימר ואנימציה משלו, ובלי memo הוא צויר מחדש בכל רינדור
// של מסך הבית — כלומר בכל לחיצה, בכל מעבר focus ובכל שינוי חיפוש.
const HeroBanner = memo(function HeroBanner({movies, onPlay, onInfo}) {
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
              <TvFocusable style={styles.heroBtnPlay} activeOpacity={0.8} onPress={() => onPlay(movie)}>
                <Text style={styles.heroBtnPlayText}>▶ צפה</Text>
              </TvFocusable>
              <TvFocusable style={styles.heroBtnInfo} activeOpacity={0.8} onPress={() => onInfo(movie)}>
                <Text style={styles.heroBtnInfoText}>מידע נוסף</Text>
              </TvFocusable>
            </View>
          </View>
        </ImageBackground>
      ) : (
        <View style={[styles.heroBg, {backgroundColor: '#111'}]}>
          <View style={styles.heroContent}>
            <Text style={styles.heroTitle}>{movie.series_name || movie.title}</Text>
            <View style={styles.heroBtns}>
              <TvFocusable style={styles.heroBtnPlay} activeOpacity={0.8} onPress={() => onPlay(movie)}>
                <Text style={styles.heroBtnPlayText}>▶ צפה</Text>
              </TvFocusable>
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
});

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

const MovieCard = memo(function MovieCard({item, onPress, hasTVPreferredFocus = false}) {
  if (!item || typeof item !== 'object') return null;
  const isLive = !!item.is_live;
  const displayTitle = String(item.name || item.title || '');
  if (!displayTitle) return null;
  // בטלוויזיה חובה שיהיה סימון ברור לאן ה-focus הגיע — אחרת נראה כאילו השלט
  // "לא עובד". onFocus/onBlur קיימים רק ב-TV; בטלפון הם פשוט לא נורים.
  const [focused, setFocused] = useState(false);
  const borderColor = focused ? '#fff' : (isLive ? '#e50914' : 'transparent');
  const borderWidth = focused ? 3 : (isLive ? 2 : 0);
  return (
    <TvFocusable
      style={[styles.card, {width: CARD_W}, focused && styles.cardFocused]}
      onPress={() => onPress(item)}
      hasFocus={hasTVPreferredFocus}
      onFocusChange={setFocused}>
      <View style={[styles.cardImg, {height: CARD_H, borderColor, borderWidth}]}>
        {item.thumbnail_url ? (
          <Image source={{uri: item.thumbnail_url}} style={isLive ? styles.cardImgLive : styles.cardImgInner} resizeMode={isLive ? 'contain' : 'cover'} fadeDuration={200} />
        ) : (
          <View style={styles.noThumb}><Text style={styles.thumbEmoji}>{isLive ? '📡' : '🎬'}</Text></View>
        )}
        {item.isSeries && <View style={styles.badge}><Text style={styles.badgeText}>סדרה</Text></View>}
        {isLive && <View style={[styles.badge, styles.liveBadge]}><Text style={styles.badgeText}>🔴 LIVE</Text></View>}
      </View>
      <Text style={styles.cardTitle} numberOfLines={2}>{displayTitle}</Text>
    </TvFocusable>
  );
});

// ── NetflixRow ────────────────────────────────────────────────────────────────

const NetflixRow = memo(function NetflixRow({title, items, onPress, isLiveRow, firstRow = false}) {
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
        renderItem={({item, index}) => (
          <MovieCard item={item} onPress={onPress}
            hasTVPreferredFocus={IS_TV && firstRow && index === 0} />
        )}
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
  const [liveChannel, setLiveChannel] = useState(null);   // דף הערוץ החי הפתוח
  // חיפוש בטלוויזיה: המרובע נעצר על העטיפה, ולחיצה מרכזית מרימה את החסימה
  // ומעבירה focus לתיבה — כך המקלדת נפתחת דרך RN, שאמין יותר מפתיחה ידנית.
  const searchRef = useRef(null);
  const [searchTyping, setSearchTyping] = useState(false);
  useEffect(() => {
    if (searchTyping) {
      const t = setTimeout(() => searchRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
  }, [searchTyping]);
  const [user, setUser] = useState(null);
  const [showSignIn, setShowSignIn] = useState(false);
  const [showCatModal, setShowCatModal] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  // סימון focus לפקדי הסרגל העליון בטלוויזיה (בטלפון נשאר תמיד false)
  const [userBtnFocus, setUserBtnFocus] = useState(false);
  const [catsBtnFocus, setCatsBtnFocus] = useState(false);
  const [clearCatFocus, setClearCatFocus] = useState(false);
  const [showDonation, setShowDonation] = useState(false);
  // אישור יציאה — בטלוויזיה בלבד. ראה את המטפל ב-hardwareBackPress.
  const [showExit, setShowExit] = useState(false);
  const donationCallback = useRef(null);
  const [showTgTip, setShowTgTip] = useState(false);
  const [showSupport, setShowSupport] = useState(false);
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
  // טעינה דו-שלבית: קודם fetchMoviesFast() מביא רק את 800 החדשים (payload קטן,
  // ציור מיידי), המשתמש רואה תוכן מיד; ואז ברקע fetchMovies() משלים את כל
  // הקטלוג. אם כבר יש cache חם — הולכים ישר למלא בלי הבהוב.
  const _hydratedRef = useRef(false);
  const load = useCallback(async (refresh = false, loggedInUser = null) => {
    if (refresh) { clearCache(); _hydratedRef.current = false; setRefreshing(true); }
    const histP = loggedInUser ? fetchHistory(loggedInUser.id) : Promise.resolve([]);
    try {
      if (!_hydratedRef.current) {
        // שלב 1 — ציור מהיר
        const fast = await fetchMoviesFast();
        if (fast && fast.length) setMovies(fast);
        setLoading(false);
        // שלב 2 — קטלוג מלא ברקע
        fetchMovies().then(full => {
          if (full && full.length) { setMovies(full); _hydratedRef.current = true; }
        }).catch(() => {});
      } else {
        const full = await fetchMovies();
        if (full && full.length) setMovies(full);
      }
      const hist = await histP;
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

  // חזרה מהנגן: לסרט בודד סוגרים את חלון הפרטים (אין לאן לחזור, וההשארה
  // גורמת להבהוב). לסדרה *משאירים אותו פתוח* — הצופה סיים פרק ורוצה לבחור
  // את הבא, וסגירה זרקה אותו למסך הבית ואילצה אותו לחפש את הסדרה מחדש.
  useEffect(() => {
    const unsub = navigation.addListener('focus', () => {
      setDetailItem(cur => (cur && cur.series_name ? cur : null));
    });
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

  // נרמול חיפוש — זהה לזה שבאתר. חיפוש תת-מחרוזת פשוט על הכותרת בלבד החמיץ
  // כמעט הכל: ניקוד, גרשיים, שם באנגלית, וכל חיפוש של יותר ממילה אחת שלא
  // מופיעה כרצף מדויק ("דרגון סופר" לא מצא "דרגון בול סופר").
  const norm = s => (s == null ? '' : String(s)).toLowerCase()
    .replace(/[\u0591-\u05C7]/g, '')                        // ניקוד עברי
    .replace(/["'`\u05F3\u05F4\u2018\u2019\u201C\u201D]/g, '')  // גרשיים
    .replace(/\s+/g, ' ').trim();
  // החיפוש רץ על השאילתה המושהית ולא על כל הקשה. בלי זה כל אות גררה סינון
  // של כל הקטלוג (כ-11,700 פריטים) על ה-thread של ה-JS, וההקלדה נתקעה.
  const [query, setQuery] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setQuery(search), 180);
    return () => clearTimeout(t);
  }, [search]);

  // מפתח חיפוש מנורמל, פעם אחת לכל קטלוג. קודם norm() רץ מחדש על ארבעה
  // שדות של כל פריט בכל הקשה — כלומר מיליוני פעולות regex לכל אות.
  const searchHay = useMemo(() => {
    const map = new Map();
    (Array.isArray(movies) ? movies : []).forEach(m => {
      if (m && m.id != null) {
        map.set(m.id, norm([m.title, m.name, m.series_name, m.en_title, m.original_title]
          .filter(Boolean).join(' ')));
      }
    });
    return map;
  }, [movies]);

  const qTokens = useMemo(
    () => norm(query).split(' ').filter(Boolean), [query]);

  const matchItem = useCallback(m => {
    if (!qTokens.length) return true;
    if (!m) return false;
    const hay = searchHay.get(m.id)
      ?? norm([m.title, m.name, m.series_name, m.en_title, m.original_title]
        .filter(Boolean).join(' '));
    return qTokens.every(t => hay.includes(t));      // כל מילה, בכל סדר
  }, [qTokens, searchHay]);

  const getItemsForCategory = useCallback(cat => {
    if (cat === 'שידורים חיים') {
      if (!Array.isArray(liveChannels)) return [];
      return liveChannels
        .filter(ch => {
          if (!ch) return false;
          return matchItem(ch);
        });
    }
    if (cat === 'היסטוריה') {
      if (!Array.isArray(history) || !Array.isArray(movies)) return [];
      return history.map(h => h && movies.find(m => m && m.id === h.media_id)).filter(Boolean);
    }
    if (cat === DOWNLOADS_CATEGORY) {
      if (!Array.isArray(downloads)) return [];
      return downloads.map(d => {
        try {
          return d ? downloadEntryToMovie(d) : null;
        } catch {
          return null;
        }
      }).filter(Boolean);
    }
    if (!Array.isArray(movies)) return [];
    const seen = {};
    const result = [];
    // שידורים חיים יושבים ברשימה נפרדת, והלולאה למטה מדלגת עליהם (m.is_live).
    // לכן חיפוש בקטגוריית "הכל" לא החזיר אף ערוץ — הם היו מגיעים רק כשבוחרים
    // במפורש את קטגוריית השידורים החיים. בחיפוש מצרפים אותם לתוצאות.
    if (cat === 'הכל' && qTokens.length && Array.isArray(liveChannels)) {
      liveChannels.forEach(ch => {
        if (ch && matchItem(ch)) result.push({...ch, is_live: true});
      });
    }
    movies.forEach(m => {
      if (!m || m.is_live) return;
      const title = m.title || '';
      const seriesName = m.series_name || '';
      const hit = matchItem(m);
      if (!hit || (cat !== 'הכל' && m.category !== cat)) return;
      if (seriesName) {
        if (!seen[seriesName] && seriesMap && seriesMap[seriesName]) {
          seen[seriesName] = true;
          const seriesItem = seriesMap[seriesName];
          if (seriesItem && seriesItem.id && seriesItem.name) {
            result.push({...seriesItem});
          }
        }
      } else {
        if (m.id && m.title) {
          result.push({...m, isSeries: false});
        }
      }
    });
    return result;
  }, [movies, liveChannels, history, seriesMap, matchItem, qTokens, downloads]);

  const netflixRows = useMemo(() => {
    // בזמן חיפוש המסך מציג רשת תוצאות, לא את השורות האלה. בלי היציאה
    // המוקדמת הן חושבו מחדש בכל הקשה — עשרות קטגוריות × כל הקטלוג — בלי
    // שאף אחד רואה אותן.
    if (qTokens.length) return [];
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
  }, [liveChannels, history, movies, allCategories, getItemsForCategory, qTokens]);

  // כפתור "חזור" בשלט. בלי זה כל לחיצה הגיעה ישר לניווט, ומכיוון שמסך הבית
  // הוא השורש — האפליקציה נסגרה ("הוא מנתק אותי מהאפליקציה"). חלון פרטי הסרט
  // הוא View רגיל ולא Modal, ולכן הוא גם לא נסגר מעצמו. כאן סוגרים שכבה אחת
  // בכל לחיצה, ורק כשאין מה לסגור נותנים לאנדרואיד לצאת כרגיל.
  // המאזין הזה רשום כל עוד מסך הבית *מותקן*, לא רק כשהוא מוצג — ומסך הבית
  // נשאר מותקן מתחת לנגן ולמסך הסדרה. לכן לחיצה על "חזור" בתוך פרק הגיעה
  // לכאן, לא מצאה שכבה לסגור, והציגה את שאלת היציאה מהאפליקציה במקום לחזור
  // אחורה; הלחיצה הבאה רק סגרה את השאלה, ומכאן ההרגשה ש"לא מגיב". כשהמסך
  // אינו במוקד מחזירים false, וההחלטה עוברת לניווט שיודע לחזור אחורה.
  const isFocused = useIsFocused();
  useEffect(() => {
    const onBack = () => {
      if (!isFocused) return false;
      if (showExit) { setShowExit(false); return true; }
      if (liveChannel) { setLiveChannel(null); return true; }
      if (showDonation) { setShowDonation(false); donationCallback.current = null; return true; }
      if (detailItem) { setDetailItem(null); return true; }
      if (showCatModal) { setShowCatModal(false); return true; }
      if (showUserMenu) { setShowUserMenu(false); return true; }
      if (showSupport) { setShowSupport(false); return true; }
      if (search) { setSearch(''); return true; }
      if (category !== 'הכל') { setCategory('הכל'); return true; }
      // אין יותר מה לסגור — כאן אנדרואיד סוגר את האפליקציה. בטלוויזיה זה קורה
      // בלחיצה אחת על השלט, בלי שום אזהרה, ולכן צופים נזרקו החוצה באמצע. שואלים
      // קודם. בטלפון משאירים את התנהגות ה"אחורה" הרגילה שמשתמשים מצפים לה.
      if (IS_TV) { setShowExit(true); return true; }
      return false;
    };
    const sub = BackHandler.addEventListener('hardwareBackPress', onBack);
    return () => sub.remove();
  }, [isFocused, showDonation, detailItem, liveChannel, showCatModal, showUserMenu, showSupport, search, category, showExit]);

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
      // ערוץ חי נפתח לדף שלו — תמונה, מה משודר עכשיו, ולוח השידורים — ולא
      // ישר לנגן. קפיצה ישירה לשידור לא נותנת שום דרך לדעת מה רואים.
      if (item.is_live) setLiveChannel(item);
      else setDetailItem(item);
    });
  }, [showDonationModal, playDownloadedItem]);

  const playLiveChannel = useCallback(ch => {
    setLiveChannel(null);
    navigation.navigate('Player', {
      movie: {
        ...ch,
        is_live: true,
        type: ch.type || 'direct',
        video_url: ch.video_url || ch.url || '',
        title: ch.title || ch.name || 'שידור חי',
      },
      userId: user?.id || null,
    });
  }, [navigation, user]);

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
        {/* focus התחלתי: בלעדיו הלחיצה הראשונה בשלט לא פוגעת בכלום, והמשתמש
            נאלץ ללחוץ קודם חץ למטה כדי ש"יתפוס" — בדיוק מה שדווח ("לוחץ
            בפעם הראשונה, הוא לא מגיב"). */}
        <TvFocusable style={styles.googleBtn} onPress={startSignIn} activeOpacity={0.8}
          hasFocus={IS_TV}>
          <Text style={styles.googleBtnText}>🔑 כניסה עם Google</Text>
        </TvFocusable>
        <TvFocusable
          style={styles.skipBtn}
          onPress={async () => {
            await AsyncStorage.setItem(SEEN_LOGIN_KEY, '1').catch(() => {});
            setShowSignIn(false);
          }}>
          <Text style={styles.skipBtnText}>המשך ללא כניסה</Text>
        </TvFocusable>
        {/* מדיניות Google Play מחייבת קישור נגיש לתנאים ולפרטיות במסך הכניסה,
            והמסך הזה מוצג עוד לפני שיש תפריט משתמש — אחרת אורח לא מגיע לתנאים כלל. */}
        <Text style={styles.signInLegal}>
          בכניסה או בהמשך אתה מסכים ל
          <Text style={styles.signInLegalLink}
                onPress={() => navigation.navigate('Legal', {doc: 'terms'})}> תנאי השימוש </Text>
          ול
          <Text style={styles.signInLegalLink}
                onPress={() => navigation.navigate('Legal', {doc: 'privacy'})}>מדיניות הפרטיות</Text>
        </Text>
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

  const isNetflixMode = category === 'הכל' && !query;
  const gridItems = isNetflixMode ? [] : getItemsForCategory(category);

  const TopBar = (
    <View style={styles.topBar}>
      <Text style={styles.appTitle}>ZOVEX</Text>

      {/* בטלוויזיה תיבת הטקסט עצמה לא מקבלת focus מה-D-pad (אחרת השלט נתקע
          בתוכה); במקום זה המרובע נעצר על העטיפה, ולחיצה מרכזית מעבירה את
          ה-focus פנימה ופותחת את המקלדת. בטלפון אין עטיפה ושום דבר לא משתנה. */}
      <TvFocusable
        style={styles.searchTvWrap}
        allowChildFocus={searchTyping}
        onPress={() => setSearchTyping(true)}>
        <Animated.View style={[styles.searchWrapper, {borderColor: searchBorderColor}]}>
          <TextInput
            ref={searchRef}
            style={styles.searchInput}
            placeholder="חיפוש..."
            placeholderTextColor="rgba(255,255,255,0.3)"
            value={search}
            onChangeText={handleSearchChange}
            onFocus={onSearchFocus}
            onBlur={() => { setSearchTyping(false); onSearchBlur && onSearchBlur(); }}
            textAlign="right"
          />
        </Animated.View>
      </TvFocusable>

      {user ? (
        <TvFocusable
          onPress={() => setShowUserMenu(true)}
          onFocusChange={setUserBtnFocus}
          style={[styles.userBtn, userBtnFocus && styles.tvFocusRing]}>
          {user.picture ? (
            <Image source={{uri: user.picture}} style={styles.userAvatar} />
          ) : (
            <View style={styles.userAvatarFallback}>
              <Text style={{color: '#fff', fontSize: 13, fontWeight: '700'}}>
                {(user.given_name || user.name || '?')[0]}
              </Text>
            </View>
          )}
        </TvFocusable>
      ) : (
        <TvFocusable
          onPress={startSignIn}
          onFocusChange={setUserBtnFocus}
          style={[styles.signInBtn, userBtnFocus && styles.tvFocusRing]}>
          <Text style={styles.signInTxt}>כניסה</Text>
        </TvFocusable>
      )}
    </View>
  );

  const CatsButton = (
    <View style={styles.catsRow}>
      {category !== 'הכל' && (
        <TvFocusable
          onPress={() => { setCategory('הכל'); setSearch(''); }}
          onFocusChange={setClearCatFocus}
          style={[styles.activeCatChip, clearCatFocus && styles.tvFocusRing]}>
          <Text style={styles.activeCatChipTxt}>✕  {category}</Text>
        </TvFocusable>
      )}
      <TvFocusable
        onPress={() => setShowCatModal(true)}
        onFocusChange={setCatsBtnFocus}
        style={[styles.catsModalBtn, catsBtnFocus && styles.tvFocusRing]}>
        <Text style={styles.catsModalBtnTxt}>≡  קטגוריות</Text>
      </TvFocusable>
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
            <TvFocusable
              key={c}
              onPress={() => { setCategory(c); setSearch(''); setShowCatModal(false); }}
              style={styles.catOverlayItem}
              activeOpacity={0.65}>
              <Text style={[styles.catOverlayText, category === c && styles.catOverlayTextActive]}>
                {c}
              </Text>
            </TvFocusable>
          ))}
        </ScrollView>
        <TvFocusable style={styles.catCloseBtn} onPress={() => setShowCatModal(false)} activeOpacity={0.85}>
          <Text style={styles.catCloseTxt}>✕</Text>
        </TvFocusable>
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
          <TvFocusable
            style={styles.menuItem}
            onPress={() => { setShowUserMenu(false); setCategory('היסטוריה'); setSearch(''); }}>
            <Text style={styles.menuItemText}>📋  היסטוריית צפייה</Text>
          </TvFocusable>
          <TvFocusable
            style={styles.menuItem}
            onPress={() => { setShowUserMenu(false); navigation.navigate('Legal'); }}>
            <Text style={styles.menuItemText}>📄  מידע ותנאים</Text>
          </TvFocusable>
          <TvFocusable
            style={styles.menuItem}
            onPress={() => { setShowUserMenu(false); Linking.openURL(DISCORD_URL).catch(() => {}); }}>
            <Text style={styles.menuItemText}>💬  שרת הדיסקורד</Text>
          </TvFocusable>
          <TvFocusable
            style={styles.menuItem}
            onPress={() => { setShowUserMenu(false); signOut(); }}>
            <Text style={[styles.menuItemText, {color: '#e50914'}]}>🚪  יציאה מהחשבון</Text>
          </TvFocusable>
        </View>
      </TouchableOpacity>
    </Modal>
  );

  // אלמנטים יציבים ל-FlatList. כשהם נכתבים inline הם נוצרים מחדש בכל רינדור,
  // והרשימה מחשיבה אותם כשונים ומציירת מחדש את הכותרת, התחתית והשורות
  // הגלויות — בכל לחיצה ובכל תזוזת focus בשלט.
  const heroHeader = useMemo(
    () => <HeroBanner movies={movies} onPlay={handleHeroPlay} onInfo={handleHeroInfo} />,
    [movies, handleHeroPlay, handleHeroInfo],
  );
  const homeFooter = useMemo(() => <HomeFooter navigation={navigation} />, [navigation]);
  const renderNetflixRow = useCallback(
    ({item: row, index}) => (
      <NetflixRow title={row.title} items={row.items} isLiveRow={row.isLiveRow}
                  onPress={handleItemPress} firstRow={index === 0} />
    ),
    [handleItemPress],
  );
  const renderGridItem = useCallback(
    ({item, index}) => (
      <MovieCard item={item} onPress={handleItemPress} hasTVPreferredFocus={IS_TV && index === 0} />
    ),
    [handleItemPress],
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
          key="netflix-rows"
          data={netflixRows}
          keyExtractor={row => row.title}
          renderItem={renderNetflixRow}
          ListHeaderComponent={heroHeader}
          ListFooterComponent={homeFooter}
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
            key={`search-grid-${NUM_COLS}`}
            data={Array.isArray(gridItems) ? gridItems.filter(item => item && item.id) : []}
            keyExtractor={item => String(item?.id || '')}
            numColumns={NUM_COLS}
            contentContainerStyle={styles.grid}
            initialNumToRender={9}
            maxToRenderPerBatch={9}
            windowSize={5}
            removeClippedSubviews
            refreshControl={
              <RefreshControl refreshing={refreshing} onRefresh={() => load(true, user)} tintColor="#e50914" />
            }
            renderItem={renderGridItem}
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

      {liveChannel && (
        <LiveChannelModal
          channel={liveChannel}
          onPlay={playLiveChannel}
          onClose={() => setLiveChannel(null)}
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

      <AdBanner />

      {/* Telegram floating bubble */}
      <View style={styles.tgBubbleWrap} pointerEvents="box-none">
        {/* הטיפ הצף הוא רכיב מגע: הוא יושב מעל התוכן ויש לו X קטן שאי אפשר
            להגיע אליו בשלט ("אי אפשר ללחוץ עליו כי זה לא טאצ'"). בטלוויזיה
            פשוט לא מציגים אותו — כפתור התמיכה עצמו נשאר נגיש בניווט. */}
        {showTgTip && !IS_TV && (
          <View style={styles.tgTip}>
            <TvFocusable
              style={styles.tgTipClose}
              onPress={() => {
                setShowTgTip(false);
                AsyncStorage.setItem(TG_TIP_KEY, '1').catch(() => {});
              }}
              hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}>
              <Text style={styles.tgTipCloseTxt}>✕</Text>
            </TvFocusable>
            <Text style={styles.tgTipTitle}>לחצו כאן לתמיכה 💬</Text>
            <Text style={styles.tgTipSub}>או להוספת סרט חדש</Text>
          </View>
        )}
        <TvFocusable
          style={styles.tgBtn}
          activeOpacity={0.85}
          onPress={() => {
            setShowTgTip(false);
            AsyncStorage.setItem(TG_TIP_KEY, '1').catch(() => {});
            setShowSupport(true);
          }}>
          <Text style={styles.tgBtnIcon}>➤</Text>
          <Text style={styles.tgBtnLabel}>תמיכה</Text>
        </TvFocusable>
      </View>

      <SupportModal
        visible={showSupport}
        onClose={() => setShowSupport(false)}
        user={user}
      />

      <UpdateDialog />

      <Modal
        visible={showDonation}
        transparent
        animationType="fade"
        onRequestClose={() => { setShowDonation(false); donationCallback.current = null; }}>
        <View style={styles.donOverlay}>
          <View style={styles.donCard}>
            {/* X לסגירה — נגיש גם בשלט וגם באצבע, כדי שתמיד תהיה יציאה ברורה */}
            <TvFocusable style={styles.donClose} onPress={handleDonationContinue}>
              <Text style={styles.donCloseTxt}>✕</Text>
            </TvFocusable>
            <Text style={styles.donEmoji}>🎬</Text>
            <Text style={styles.donTitle}>עזרו לנו לשפר את האפליקציה</Text>
            <Text style={styles.donBody}>
              {'ZOVEX פועל ללא מטרות רווח ובהתנדבות מלאה.\nתרומה קטנה תעזור לנו לשפר את איכות האפליקציה,\nלשדרג את הנגנים ולהוסיף עוד תכנים כיפיים לצפייה 💙'}
            </Text>
            <TvFocusable
              style={styles.donBitBtn}
              activeOpacity={0.85}
              onPress={() => Linking.openURL('https://www.bitpay.co.il/app/me/F062649F-7124-4CDF-88DD-A1FEA14185EB').catch(() => {})}>
              <Text style={styles.donBitTxt}>💳 תרום בביט</Text>
            </TvFocusable>
            <TvFocusable
              style={styles.donContinueBtn}
              activeOpacity={0.85}
              /* בטלוויזיה ה-focus מתחיל דווקא כאן ולא על כפתור התרומה: בשלט
                 אין "לחיצה מחוץ לחלון", ולכן אם ה-focus נוחת על התרומה המשתמש
                 נתקע ולא מצליח לצאת מהחלון בכלל. */
              hasFocus={IS_TV}
              onPress={handleDonationContinue}>
              <Text style={styles.donContinueTxt}>המשך לצפייה</Text>
            </TvFocusable>
          </View>
        </View>
      </Modal>

      {/* אישור יציאה. בשלט אין "לחיצה מחוץ לחלון", ולכן ה-focus חייב להתחיל
          על "לא" — הכפתור הבטוח — ושתי האפשרויות חייבות להיות נגישות. */}
      <Modal
        visible={showExit}
        transparent
        animationType="fade"
        onRequestClose={() => setShowExit(false)}>
        <View style={styles.donOverlay}>
          <View style={styles.exitCard}>
            <Text style={styles.donEmoji}>👋</Text>
            <Text style={styles.donTitle}>לצאת מ-ZOVEX?</Text>
            <View style={styles.exitRow}>
              <TvFocusable
                style={styles.exitNoBtn}
                activeOpacity={0.85}
                hasFocus={IS_TV}
                onPress={() => setShowExit(false)}>
                <Text style={styles.exitNoTxt}>לא, להישאר</Text>
              </TvFocusable>
              <TvFocusable
                style={styles.exitYesBtn}
                activeOpacity={0.85}
                onPress={() => { setShowExit(false); BackHandler.exitApp(); }}>
                <Text style={styles.exitYesTxt}>כן, לצאת</Text>
              </TvFocusable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: '#0a0a0a'},
  exitCard: {
    backgroundColor: '#161616', borderRadius: 18, paddingVertical: 28,
    paddingHorizontal: 26, width: '86%', maxWidth: 460, alignItems: 'center',
  },
  exitRow: {flexDirection: 'row-reverse', gap: 12, marginTop: 22},
  exitNoBtn: {
    backgroundColor: '#e50914', borderRadius: 12,
    paddingVertical: 14, paddingHorizontal: 26,
  },
  exitNoTxt: {color: '#fff', fontSize: 16, fontWeight: '800'},
  exitYesBtn: {
    backgroundColor: '#2a2a2a', borderRadius: 12,
    paddingVertical: 14, paddingHorizontal: 26,
  },
  exitYesTxt: {color: '#ddd', fontSize: 16, fontWeight: '700'},
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
  signInLegal: {color: '#555', fontSize: 12, textAlign: 'center', marginTop: 26, paddingHorizontal: 30, lineHeight: 19},
  signInLegalLink: {color: '#8ab4f8', fontWeight: '600'},

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
  // העטיפה יורשת את ה-flex של תיבת החיפוש כדי שהסרגל העליון יישאר בדיוק
  // כפי שהיה; היא רק מוסיפה שכבה שאפשר לנווט אליה בשלט.
  searchTvWrap: {flex: 1, borderRadius: 20},
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
  // הדגשת ה-focus בטלוויזיה: הכרטיס ה"נבחר" עולה מעל השכנים ומקבל רקע בהיר
  // קל, בנוסף למסגרת הלבנה על התמונה. בלי scale כדי לא לחתוך/לחפוף שכנים.
  cardFocused: {backgroundColor: '#2a2a2c', zIndex: 3, elevation: 6},
  // טבעת ה-focus לפקדים בסרגל העליון — אותו שפה ויזואלית כמו הכרטיסים
  tvFocusRing: {borderWidth: 2, borderColor: '#fff', borderRadius: 8},
  cardImg: {width: '100%', borderRadius: 10, overflow: 'hidden', backgroundColor: '#1c1c1e'},
  cardImgInner: {width: '100%', height: '100%', resizeMode: 'cover'},
  cardImgLive: {width: '100%', height: '100%', resizeMode: 'contain', padding: 8},
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
    // bottom מוגבה כדי לא להיחסם ע"י באנר הפרסומת הקבוע בתחתית (AdBanner)
    position: 'absolute', bottom: 78, zIndex: 1000,
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
  donClose: {
    position: 'absolute', top: 8, right: 8, zIndex: 10,
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: 'rgba(255,255,255,0.12)',
    alignItems: 'center', justifyContent: 'center',
  },
  donCloseTxt: {color: '#fff', fontSize: 16, fontWeight: '700', lineHeight: 18},
  donCard: {backgroundColor: '#111', borderRadius: 24, padding: 28, width: '100%', alignItems: 'center', borderWidth: 1, borderColor: '#222'},
  donEmoji: {fontSize: 32, marginBottom: 10},
  donTitle: {fontSize: 20, fontWeight: '900', color: '#fff', textAlign: 'center', marginBottom: 10},
  donBody: {fontSize: 14, color: '#aaa', textAlign: 'center', lineHeight: 24, marginBottom: 20},
  donBitBtn: {width: '100%', backgroundColor: '#0d7a5f', borderRadius: 14, paddingVertical: 16, alignItems: 'center', marginBottom: 10},
  donBitTxt: {color: '#fff', fontSize: 16, fontWeight: '700'},
  donContinueBtn: {width: '100%', backgroundColor: '#1e1e1e', borderRadius: 14, paddingVertical: 14, alignItems: 'center', borderWidth: 1, borderColor: '#333'},
  donContinueTxt: {color: '#888', fontSize: 14},
});
