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
  Animated,
  AppState,
  Platform,
  BackHandler,
  Share,
  PanResponder,
} from 'react-native';
import {GoogleSignin} from '@react-native-google-signin/google-signin';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  fetchMovies,
  fetchMoviesFast,
  fetchItemDetail,
  fetchHistory,
  removeFromHistory,
  clearHistory,
  removeProgress,
  fetchTrailerKey,
  fetchFavoriteIds,
  addFavorite,
  removeFavorite,
  clearCache,
  isCatalogStale,
} from '../api/movies';
import {WebView} from 'react-native-webview';
import {catName, genreName, isRTL, pinLeft, pinRight, t} from '../i18n';
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
import {verifyPanelCode} from '../api/savedUpload';
import TvFocusable from '../components/TvFocusable';
import {colors, font, elevation, radius} from '../theme/tokens';
import {DarkGradient, EmptyState} from '../theme/components';
import LiveChannelModal from '../components/LiveChannelModal';
import AdBanner from '../components/AdBanner';
import SupportModal from '../components/SupportModal';
import UpdateDialog from '../components/UpdateDialog';
import {NAV_HOME, NAV_HOME_ON, NAV_SEARCH, NAV_SEARCH_ON, NAV_HEART, NAV_HEART_ON,
        NAV_USER, NAV_USER_ON} from '../components/navIcons';
import {DISCORD_URL, TELEGRAM_URL} from '../config/links';
import {groupLiveByGenre} from '../utils/liveGenres';

const DOWNLOADS_CATEGORY = 'ההורדות שלי';

// דלי שנים לסינון בדף החיפוש הייעודי (טלפון) — ראה ההסבר המלא ליד
// matchesYearFilter.
const YEAR_FILTERS = [
  {key: 'all', label: 'הכל'},
  {key: '2020', label: '2020+'},
  {key: '2010', label: '2010–2019'},
  {key: '2000', label: '2000–2009'},
  {key: 'old', label: 'לפני 2000'},
];

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
// בטלוויזיה שכבת רקע לוחצת היא יעד focus מיותר; בטלפון היא הדרך לסגור.
const OverlayWrap = IS_TV
  ? ({style, children}) => <View style={style}>{children}</View>
  : TouchableOpacity;
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
// כל כמה זמן לשאול את השרת אם התוכן השתנה, בזמן שהמסך פתוח. השאלה עצמה היא
// ~25 בתים (/content/version), והקטלוג נמשך רק כשהמספר זז — כלומר בפועל
// אחרי עריכה בפאנל ולא כל דקה.
const CATALOG_POLL_MS = 60 * 1000;

GoogleSignin.configure({
  scopes: ['profile', 'email'],
  offlineAccess: false,
});

// ── Movie Detail Modal ────────────────────────────────────────────────────────

// זמן שנותר בפורמט קריא: "45 שנ׳" / "3:20" / "1:05:00".
function fmtEta(sec) {
  if (sec == null || !isFinite(sec) || sec < 0) return null;
  if (sec < 60) return `${Math.round(sec)} שנ׳`;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.round(sec % 60);
  const pad = n => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function DownloadControl({item, compact, downloadedIds, downloadingId, downloadProgress, onDownload, onDeleteDownload}) {
  if (!item || !isItemDownloadable(item)) return null;
  const id = String(item.id);
  const isThisDownloading = downloadingId === id;
  const isDownloaded = downloadedIds.has(id);

  if (isThisDownloading) {
    const pct = Math.round((downloadProgress?.pct || 0) * 100);
    // אין יותר שלב "מצפין" — הקובץ נשמר כמו שהוא והניגון מיידי. נשאר רק
    // "מוריד", עם כמה סטטיסטיקות חיות: כמה מתוך כמה, מהירות, וזמן שנותר.
    // הקבצים גדולים (לרוב 1GB+) על קו איטי, ולכן האחוז לבדו יכול להיראות
    // תקוע — ספירת ה-MB והמהירות זזות תוך שנייה.
    const mb = downloadProgress?.contentLength
      ? `${Math.round((downloadProgress.bytesWritten || 0) / 1048576)}/${Math.round(downloadProgress.contentLength / 1048576)}MB`
      : null;
    const spd = downloadProgress?.speed > 0
      ? `${(downloadProgress.speed / 1048576).toFixed(1)}MB/s` : null;
    const eta = fmtEta(downloadProgress?.eta);
    const parts = [`מוריד ${pct}%`, mb, spd, eta ? `נותרו ${eta}` : null].filter(Boolean);
    return (
      <View style={[mdStyles.dlBtn, compact && mdStyles.dlBtnCompact]}>
        <ActivityIndicator size="small" color={colors.primary} />
        {!compact && (
          <Text style={mdStyles.dlBtnTxt}>{parts.join(' · ')}</Text>
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
  isFavorite, onToggleFavorite,
  isInHistory, onRemoveFromHistory,
}) {
  // ── טריילר ────────────────────────────────────────────────────────────
  // מנוגן במקום הפוסטר כשיש. הפוסטר נשאר ברירת המחדל ולא מוחלף עד שהמפתח
  // חוזר בפועל, כך שפריט בלי טריילר נראה בדיוק כמו קודם ואין הבהוב.
  const [trailerKey, setTrailerKey] = useState(null);
  const [trailerOff, setTrailerOff] = useState(false);   // הצופה סגר אותו
  useEffect(() => {
    let alive = true;
    setTrailerKey(null); setTrailerOff(false);
    if (item?.id && !item.is_live) {
      fetchTrailerKey(item.id).then(k => { if (alive) setTrailerKey(k); });
    }
    return () => { alive = false; };
  }, [item?.id, item?.is_live]);

  // ── פרק מסוים שנלחץ, ולא הסדרה כולה ────────────────────────────────
  //
  // מהמשך צפייה, מההורדות ומהמועדפים מגיע פרק בודד, עם עונה ומספר. עד
  // עכשיו החלון התעלם מזה: הוא נפתח תמיד על העונה הראשונה, וכפתור
  // "הפעל" ניגן את הפרק הראשון שלה. כלומר צפית בעונה 3 פרק 5, לחצת
  // "המשך", וקיבלת עונה 1 פרק 1. גם כפתור ההורדה הוריד את הפרק הראשון.
  const tappedEp = (item && !item.isSeries && item.series_name && item.episode_number)
    ? item : null;
  const [selectedSeason, setSelectedSeason] = useState(null);
  // עונה חדשה לכל פריט שנפתח. בלי האיפוס, עונה שנבחרה בחלון הקודם נשארה
  // תקועה גם כשנפתחה סדרה אחרת.
  useEffect(() => {
    setSelectedSeason(tappedEp ? (tappedEp.season_number || 1) : null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id]);
  const [showSeasonPicker, setShowSeasonPicker] = useState(false);
  // בורר העונות עבר מ-Modal שני לשכבת View רגילה (ראה ההסבר ליד
  // seasonPickerWrap) — Modal נתן "חזור" אוטומטי בחינם, View לא. בלי
  // זה "חזור" בזמן שהבורר פתוח היה נופל ישר ל-detailItem שבמסך הבית
  // וסוגר את כל חלון הפרטים, לא רק את הבורר. אותו דפוס בדיוק כמו
  // ה-BackHandler שכבר קיים ב-HomeScreen עצמו.
  useEffect(() => {
    const onBack = () => {
      if (showSeasonPicker) { setShowSeasonPicker(false); return true; }
      return false;
    };
    const sub = BackHandler.addEventListener('hardwareBackPress', onBack);
    return () => sub.remove();
  }, [showSeasonPicker]);
  const [seasonLoading, setSeasonLoading] = useState(false);
  // ה-description לא נשלח ב-/content/lite (זה השדה הכבד). כשפותחים סרט
  // מושכים אותו לפי דרישה מ-/content/item/{id}. אם הפריט כבר מכיל description
  // (למשל מ-cache ישן) — משתמשים בו כמו שהוא.
  //
  // cast נמשך באותה קריאה בדיוק — לא עוד fetch נפרד. הוא גם לא נשלח
  // ב-lite מאותה סיבה (ראה _LITE_DROP בשרת).
  const [fetchedDesc, setFetchedDesc] = useState(null);
  const [fetchedCast, setFetchedCast] = useState(null);
  useEffect(() => {
    setFetchedDesc(null);
    setFetchedCast(null);
    if (!item) return;
    // דרוש fetch גם כשיש כבר description אבל אין עדיין cast (תוכן שנוסף
    // לפני התכונה) — ממשיכים רק אם *שניהם* כבר קיימים על הפריט עצמו.
    if (item.description && item.cast) return;
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
      if (!alive || !full) return;
      if (full.description) setFetchedDesc(full.description);
      if (Array.isArray(full.cast) && full.cast.length) setFetchedCast(full.cast);
    });
    return () => { alive = false; };
  }, [item, allMovies]);
  const description = item?.description || fetchedDesc || '';
  const cast = (item?.cast && item.cast.length ? item.cast : fetchedCast) || [];

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
          {/* תמונת hero עם gradient מאחורי הכותרת (SCREEN_BY_SCREEN §3) —
              רק כשיש תמונה: בלי גב, אין על מה לשים גרדיאנט, והכותרת חוזרת
              לשבת בראש הגוף הרגיל, בלי להעמיד טקסט על רקע ריק. */}
          {item.thumbnail_url ? (
            <View style={mdStyles.thumbWrap}>
              <Image source={{uri: item.thumbnail_url}} style={mdStyles.thumb} />
              <DarkGradient />
              <View style={mdStyles.thumbTitleWrap}>
                {!!item.year && <Text style={mdStyles.year}>{item.year}</Text>}
                <Text style={mdStyles.title}>{displayTitle}</Text>
                {tappedEp ? (
                  <Text style={mdStyles.epHeading}>
                    עונה {tappedEp.season_number || 1} · פרק {tappedEp.episode_number}
                    {tappedEp.episode_title ? `  —  ${tappedEp.episode_title}` : ''}
                  </Text>
                ) : null}
              </View>
            </View>
          ) : (
            <View style={mdStyles.noThumb}>
              <Text style={{fontSize: 52}}>{item.is_live ? '📡' : '🎬'}</Text>
            </View>
          )}
          <View style={mdStyles.body}>
            {!item.thumbnail_url && (
              <>
                {!!item.year && <Text style={mdStyles.year}>{item.year}</Text>}
                <Text style={mdStyles.title}>{displayTitle}</Text>
                {tappedEp ? (
                  <Text style={mdStyles.epHeading}>
                    עונה {tappedEp.season_number || 1} · פרק {tappedEp.episode_number}
                    {tappedEp.episode_title ? `  —  ${tappedEp.episode_title}` : ''}
                  </Text>
                ) : null}
              </>
            )}
            {!!description && (
              <Text style={mdStyles.desc} numberOfLines={5}>{description}</Text>
            )}
            {trailerKey && !trailerOff && (
              <View style={mdStyles.trailerBox}>
                <View style={mdStyles.trailerHead}>
                  <Text style={mdStyles.trailerTtl}>🎬 טריילר</Text>
                  {/* TvFocusable ולא TouchableOpacity: בשלט אי אפשר היה
                      להגיע לכפתור הזה, כלומר מי שהטריילר הפריע לו נתקע איתו. */}
                  <TvFocusable onPress={() => setTrailerOff(true)} hitSlop={10}>
                    <Text style={mdStyles.trailerClose}>סגור</Text>
                  </TvFocusable>
                </View>
                {/* נגן יוטיוב מלא ולא תצוגה מקדימה: בלי autoplay ובלי השתקה
                    כפויה, עם הפקדים המקוריים ועם מסך מלא. קודם זה היה סרטון
                    מושתק שכיסה את הפוסטר ולא הגיב לשום לחיצה. */}
                {/* WebView הוא רכיב נייטיב שיכול לתפוס את ה-focus ולכלוא את
                    ה-D-pad בתוך עמוד היוטיוב. TvFocusable חוסם focus לילדים
                    (descendantFocusability = FOCUS_BLOCK_DESCENDANTS), ולכן
                    המסגרת היא עצירת focus אחת ומוגדרת במקום מלכודת. */}
                <TvFocusable style={mdStyles.trailerFrame}>
                  <WebView
                    style={mdStyles.trailerWeb}
                    // HTML מקומי עם baseUrl ולא טעינת ה-embed ישירות.
                    // WebView שטוען youtube.com/embed בכתובת מגיע בלי origin
                    // תקין, ויוטיוב דוחה את ההטמעה עם "שגיאה 153". עם baseUrl
                    // של הדומיין שלנו יש מקור חוקי וההטמעה מתקבלת.
                    originWhitelist={['*']}
                    source={{
                      baseUrl: 'https://zovex.duckdns.org',
                      html: `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body{margin:0;padding:0;background:#000;height:100%;overflow:hidden}
iframe{border:0;width:100%;height:100%;display:block}</style></head><body>
<iframe src="https://www.youtube.com/embed/${trailerKey}?playsinline=1&rel=0&modestbranding=1&fs=1&enablejsapi=1"
 allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture; fullscreen"
 allowfullscreen></iframe></body></html>`,
                    }}
                    allowsInlineMediaPlayback
                    allowsFullscreenVideo
                    mediaPlaybackRequiresUserAction={false}
                    javaScriptEnabled
                    domStorageEnabled
                    // נטרול גלילת ההורה: בלי זה ה-ScrollView בולע את הלחיצות
                    // וכלום בתוך הנגן לא מגיב — בדיוק מה שדוד תיאר.
                    nestedScrollEnabled
                    scrollEnabled={false}
                    onError={() => setTrailerOff(true)}
                    onHttpError={() => setTrailerOff(true)}
                  />
                </TvFocusable>
              </View>
            )}

            <View style={mdStyles.actionsRow}>
              <TvFocusable style={mdStyles.playBtn} activeOpacity={0.8}
                hasFocus={IS_TV}
                onPress={() => onPlayDirect(tappedEp || firstEp || item)}>
                <Text style={mdStyles.playTxt}>
                  {tappedEp ? `▶ פרק ${tappedEp.episode_number}` : '▶ הפעל'}
                </Text>
              </TvFocusable>
              {onToggleFavorite && (
                <TvFocusable
                  style={[mdStyles.favBtn, isFavorite && mdStyles.favBtnOn]}
                  activeOpacity={0.8}
                  onPress={() => onToggleFavorite(item)}>
                  <Text style={[mdStyles.favTxt, isFavorite && mdStyles.favTxtOn]}>
                    {isFavorite ? '❤' : '♡'}
                  </Text>
                </TvFocusable>
              )}
              {/* הסרה מ"המשך צפייה" / היסטוריה. מופיע רק כשהפריט שם, ולא
                  לשידור חי (שאינו נשמר בהיסטוריה). הפעולה מסירה מהרשימה
                  בלבד — התוכן נשאר בקטלוג, ואפשר לצפות בו שוב. כאן בתוך
                  חלון הפרטים, שכפתוריו כבר נגישים בשלט, ולא כ-overlay על
                  הכרטיס — שם קינון focusable בטלוויזיה אינו מובטח. */}
              {isInHistory && onRemoveFromHistory && !item.is_live && (
                <TvFocusable
                  style={mdStyles.rmBtn}
                  activeOpacity={0.8}
                  onPress={() => { onRemoveFromHistory(item); onClose(); }}>
                  <Text style={mdStyles.rmTxt}>🗑</Text>
                </TvFocusable>
              )}
              <DownloadControl
                item={tappedEp || firstEp || item}
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
            {/* שחקנים — מתחת לכפתור ההפעלה, כמו שביקש דוד. ריק כשאין נתוני
                TMDB (תוכן ישן, או לא זוהה) — מוסתר כליל, לא מציג משבצות
                ריקות. גלילה אופקית פשוטה בטלפון; בטלוויזיה מוצג סטטי
                (בלי focus לשלט) — זה תוכן נלווה, לא פעולה. */}
            {cast.length > 0 && (
              <View style={mdStyles.castSection}>
                <Text style={mdStyles.castHeader}>שחקנים</Text>
                <ScrollView horizontal showsHorizontalScrollIndicator={false}
                  contentContainerStyle={mdStyles.castRow}>
                  {cast.map((c, i) => (
                    <View key={i} style={mdStyles.castItem}>
                      {c.photo ? (
                        <Image source={{uri: c.photo}} style={mdStyles.castPhoto} />
                      ) : (
                        <View style={mdStyles.castPhotoEmpty}>
                          <Text style={{fontSize: 20}}>🎭</Text>
                        </View>
                      )}
                      <Text style={mdStyles.castName} numberOfLines={2}>{c.name}</Text>
                    </View>
                  ))}
                </ScrollView>
              </View>
            )}
          </View>
          {episodes.length > 1 && (
            <View style={mdStyles.epsSection}>
              {seasons.length > 0 && (
                <View style={mdStyles.seasonRow}>
                  {seasons.length > 1 ? (
                    <TvFocusable style={mdStyles.seasonBtn} onPress={() => setShowSeasonPicker(true)} activeOpacity={0.8}>
                      <Text style={mdStyles.seasonBtnTxt}>עונה {activeSeason} ▾</Text>
                    </TvFocusable>
                  ) : (
                    // עונה יחידה: תווית, לא כפתור. קודם השורה הוסתרה לגמרי
                    // כשהייתה עונה אחת, ולכן 82 מתוך 179 הסדרות "דילגו על
                    // אריח העונה ישר לפרקים" — מה שנראה כמו תקלה ולא כמו
                    // כוונה. עכשיו העונה תמיד מוצגת, אבל בלי לגזול תחנת
                    // focus בשלט על בחירה שאין בה מה לבחור.
                    <View style={[mdStyles.seasonBtn, mdStyles.seasonBtnStatic]}>
                      <Text style={mdStyles.seasonBtnTxt}>עונה {activeSeason}</Text>
                    </View>
                  )}
                </View>
              )}
              <Text style={mdStyles.epsHeader}>פרקים ({visibleEpisodes.length})</Text>
              {seasonLoading ? (
                <View style={{alignItems: 'center', paddingVertical: 30}}>
                  <ActivityIndicator size="large" color={colors.primary} />
                </View>
              ) : (
                visibleEpisodes.map(ep => (
                  <TvFocusable key={ep.id}
                    style={[mdStyles.epRow, tappedEp && ep.id === tappedEp.id && mdStyles.epRowCurrent]}
                    activeOpacity={0.75} onPress={() => onPlayDirect(ep)}>
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
        // [fix_season_picker_nested_modal] זה היה <Modal> שני, מקונן
        // בתוך ה-<Modal> החיצוני של MovieDetailModal עצמו. דווח מהשטח:
        // "מעבר בין עונות לא עובד", ו"השלט קופץ רק בקצוות" — בדיוק
        // התסמין שה-hasFocus למטה כבר ניסה לתקן באוגוסט, ועדיין קורה.
        //
        // התיקון ההוא נכון לעצמו, אבל הוא לא הבעיה: ב-react-native
        // (ReactModalHostView) כל <Modal> פותח חלון Dialog native
        // נפרד, עם FLAG_NOT_FOCUSABLE עד שהוא מוצג (ראה ההסבר המלא ב-
        // TvFocusableViewManager.kt). שני Dialog-ים מוערמים זה על זה
        // — וה-focus הטבעי שעדיין "תקוע" על כפתור "עונה X ▾" שבחלון
        // הראשון לא עובר נכון לחלון השני. CatModal ו-UserMenu הם כל
        // אחד Modal יחיד מתוך המסך הרגיל — לא Modal בתוך Modal — וזו
        // בדיוק הסיבה שרק הבורר הזה נשבר.
        //
        // הפתרון: בלי Modal שני בכלל. View רגיל בתוך אותו חלון —
        // אין שני Dialog-ים, אין race. אותה כיסוי מלא, אותו backdrop
        // ללחיצה-לסגירה, אותו hasFocus — שום דבר בתוך הבורר לא השתנה.
        //
        // המחיר: Modal נתן "חזור" בחינם; View לא. ראה ה-BackHandler
        // שנוסף למעלה, שסוגר רק את הבורר ולא את כל חלון הפרטים.
        <View style={mdStyles.seasonPickerWrap}>
          <TouchableOpacity style={mdStyles.seasonPickerOverlay} activeOpacity={1} onPress={() => setShowSeasonPicker(false)}>
            <View style={mdStyles.seasonPickerBox} onStartShouldSetResponder={() => true}>
              {seasons.map((s, i) => (
                <TvFocusable
                  key={s}
                  // ה-fallback ל-i === 0 חשוב: אם activeSeason אינו ברשימה
                  // (למשל עונה שנעלמה מהקטלוג) שום פריט לא היה מתאים, והבורר
                  // היה נפתח שוב בלי focus.
                  hasFocus={IS_TV && (s === activeSeason ||
                                      (!seasons.includes(activeSeason) && i === 0))}
                  style={[mdStyles.seasonPickerItem, s === activeSeason && mdStyles.seasonPickerItemActive]}
                  onPress={() => handleSeasonSelect(s)}>
                  <Text style={[mdStyles.seasonPickerTxt, s === activeSeason && mdStyles.seasonPickerTxtActive]}>עונה {s}</Text>
                </TvFocusable>
              ))}
            </View>
          </TouchableOpacity>
        </View>
      )}
    </View>
    </Modal>
  );
}

const mdStyles = StyleSheet.create({
  trailerWeb: {flex: 1, backgroundColor: '#000'},
  trailerBox: {marginBottom: 16},
  trailerHead: {flexDirection: 'row', alignItems: 'center',
                justifyContent: 'space-between', marginBottom: 8},
  trailerTtl: {color: '#fff', fontSize: 14, fontWeight: '800'},
  trailerClose: {color: colors.textMuted, fontSize: 12, fontWeight: '600'},
  // יחס 16:9 קבוע, כדי שהמסגרת לא תקפוץ בזמן הטעינה.
  // ברוחב מלא על מסך 16:9 הטריילר תופס כמעט את כל הגובה, דוחף את כפתורי
  // הניגון אל מחוץ לתצוגה, ומנוע ה-focus הגאומטרי מתקשה למצוא אותם. בטלוויזיה
  // הוא יושב כפאנל צדדי במקום להשתלט על המסך.
  trailerFrame: {width: IS_TV ? '40%' : '100%', alignSelf: 'flex-start',
                 aspectRatio: 16 / 9, maxWidth: '100%',
                 borderRadius: 12, overflow: 'hidden', backgroundColor: '#000'},
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: colors.bg,
    zIndex: 100,
  },
  sheet: {flex: 1, overflow: 'hidden', backgroundColor: colors.bg},
  closeBtn: {
    position: 'absolute', top: 14, right: 14, zIndex: 10,
    backgroundColor: colors.overlay, borderRadius: 20,
    width: 38, height: 38, justifyContent: 'center', alignItems: 'center',
  },
  closeTxt: {color: '#fff', fontSize: 14, fontWeight: '700'},
  // hero עם gradient (SCREEN_BY_SCREEN §3): thumbWrap הוא ה-view הממוקם,
  // thumb ממלא אותו לגמרי, ו-thumbTitleWrap יושב מעליו בתחתית — בדיוק
  // מבנה ה-hero שבמסך הבית, רק עם padding-bottom קטן יותר כי אין כאן
  // שני כפתורים גדולים מתחת לכותרת.
  thumbWrap: {width: '100%', height: 260},
  thumb: {...StyleSheet.absoluteFillObject, resizeMode: 'cover'},
  thumbTitleWrap: {position: 'absolute', left: 0, right: 0, bottom: 0, padding: 18, paddingBottom: 14},
  noThumb: {width: '100%', height: 200, backgroundColor: colors.surfaceElevated, justifyContent: 'center', alignItems: 'center'},
  body: {padding: 18},
  year: {
    color: 'rgba(255,255,255,0.7)', fontSize: 12, fontWeight: '700', textAlign: 'right',
    marginBottom: 2, textShadowColor: 'rgba(0,0,0,0.8)', textShadowOffset: {width: 0, height: 1},
    textShadowRadius: 6,
  },
  title: {
    color: '#fff', fontSize: 20, fontWeight: '800', textAlign: 'right', marginBottom: 8,
    textShadowColor: 'rgba(0,0,0,0.8)', textShadowOffset: {width: 0, height: 2}, textShadowRadius: 8,
  },
  epHeading: {
    color: '#ddd', fontSize: 14, fontWeight: '700', textAlign: 'right', marginTop: -4, marginBottom: 8,
    textShadowColor: 'rgba(0,0,0,0.8)', textShadowOffset: {width: 0, height: 1}, textShadowRadius: 6,
  },
  desc: {color: colors.textSecondary, fontSize: 13, lineHeight: 20, textAlign: 'right', marginBottom: 16},
  actionsRow: {flexDirection: 'row', gap: 10},
  playBtn: {flex: 1, backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 14, alignItems: 'center'},
  // לב ריק/מלא. רוחב קבוע כדי שהמעבר בין ♡ ל-❤ לא יזיז את שאר הכפתורים.
  favBtn: {width: 52, marginRight: 8, borderRadius: 12, paddingVertical: 14,
           alignItems: 'center', justifyContent: 'center',
           backgroundColor: colors.hairline},
  favBtnOn: {backgroundColor: colors.focusTint},
  favTxt: {fontSize: 20, color: colors.text},
  favTxtOn: {color: colors.primaryHi},
  rmBtn: {width: 52, borderRadius: 12, paddingVertical: 14,
          alignItems: 'center', justifyContent: 'center',
          backgroundColor: colors.hairline},
  rmTxt: {fontSize: 18, color: colors.text},
  shareBtn: {
    backgroundColor: colors.surfaceElevated, borderRadius: 12, paddingVertical: 14,
    paddingHorizontal: 18, alignItems: 'center', justifyContent: 'center',
  },
  shareTxt: {color: '#fff', fontSize: 15, fontWeight: '700'},
  playTxt: {color: '#fff', fontSize: 16, fontWeight: '800'},
  // ── שחקנים ──
  castSection: {marginTop: 18},
  castHeader: {color: colors.text, fontSize: 15, fontWeight: '800', textAlign: 'right', marginBottom: 10},
  castRow: {flexDirection: 'row', gap: 12, paddingBottom: 4},
  castItem: {width: 68, alignItems: 'center'},
  castPhoto: {width: 60, height: 60, borderRadius: 30, backgroundColor: colors.surfaceElevated},
  castPhotoEmpty: {
    width: 60, height: 60, borderRadius: 30, backgroundColor: colors.surfaceElevated,
    justifyContent: 'center', alignItems: 'center',
  },
  castName: {color: colors.textSecondary, fontSize: 11, fontWeight: '600', textAlign: 'center', marginTop: 6},
  dlBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
    backgroundColor: colors.surfaceElevated, borderRadius: 12, paddingVertical: 14, paddingHorizontal: 16,
  },
  dlBtnCompact: {
    paddingVertical: 6, paddingHorizontal: 8, borderRadius: 16, marginHorizontal: 6, minWidth: 34,
  },
  dlBtnTxt: {color: colors.text, fontSize: 13, fontWeight: '700'},
  // ירוק נשאר פונקציונלי (סטטוס "הורד") ולא הופך לאדום המותג — אדום כאן
  // היה מתפרש כשגיאה/אזהרה, לא כהצלחה.
  dlBtnDone: {backgroundColor: 'rgba(60,191,138,0.16)'},
  dlBtnDoneTxt: {color: colors.success},
  epsSection: {paddingHorizontal: 16, paddingBottom: 24},
  seasonRow: {flexDirection: 'row', justifyContent: 'flex-end', paddingTop: 14, paddingBottom: 4, borderTopWidth: 1, borderTopColor: colors.border},
  seasonBtn: {backgroundColor: colors.surfaceElevated, borderRadius: 20, paddingHorizontal: 16, paddingVertical: 8},
  // עונה יחידה — נראית כתווית ולא ככפתור, כדי שלא תזמין לחיצה שלא תעשה כלום
  seasonBtnStatic: {backgroundColor: colors.surfaceElevated, opacity: 0.85},
  seasonBtnTxt: {color: colors.text, fontSize: 14, fontWeight: '700'},
  // תופס את מקום ה-Modal שהוסר (ראה fix_season_picker_nested_modal) —
  // כיסוי מלא באותו חלון, לא Dialog נפרד. zIndex מעל sheet (שאין לו
  // אחד, כלומר 0 כברירת מחדל) מבטיח סדר ציור גם בלי תלות בסדר ה-JSX.
  seasonPickerWrap: {...StyleSheet.absoluteFillObject, zIndex: 50},
  seasonPickerOverlay: {flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'center', alignItems: 'center'},
  seasonPickerBox: {backgroundColor: colors.surfaceElevated, borderRadius: 16, overflow: 'hidden', minWidth: 180},
  seasonPickerItem: {paddingVertical: 18, paddingHorizontal: 28, alignItems: 'center'},
  seasonPickerItemActive: {backgroundColor: colors.focusTint},
  seasonPickerTxt: {color: colors.textSecondary, fontSize: 16, fontWeight: '600'},
  seasonPickerTxtActive: {color: colors.primaryHi, fontSize: 17, fontWeight: '800'},
  epsHeader: {color: colors.text, fontSize: 15, fontWeight: '800', textAlign: 'right', marginBottom: 10, paddingTop: 10},
  epRow: {flexDirection: 'row', alignItems: 'center', paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border},
  // הפרק שממנו נפתח החלון. רק הדגשה עדינה של הרקע — הפלטה לא משתנה.
  epRowCurrent: {backgroundColor: colors.focusTint, borderRadius: 8},
  epThumb: {width: 110, height: 62, borderRadius: radius.sm, resizeMode: 'cover'},
  epThumbEmpty: {width: 110, height: 62, borderRadius: radius.sm, backgroundColor: colors.surfaceElevated, justifyContent: 'center', alignItems: 'center'},
  epInfo: {flex: 1, marginHorizontal: 10},
  epNum: {color: colors.primaryHi, fontSize: 11, fontWeight: '700', textAlign: 'right'},
  epTitle: {color: colors.text, fontSize: 13, fontWeight: '600', textAlign: 'right', marginTop: 3},
  epPlayIcon: {color: colors.primary, fontSize: 14},
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
      {/* מי שקנה את ZOVEX ממישהו לא יחשוד בכך מעצמו — הוא שילם, אז
          מבחינתו זה מוצר בתשלום. לכן זה נאמר בכותרת התחתונה, שנראית
          תמיד ואינה חוסמת כלום, ולא רק בדף משפטי שאיש אינו פותח. */}
      <Text style={ftStyles.note}>{t('free.footer')}</Text>
    </View>
  );
}

const ftStyles = StyleSheet.create({
  wrap: {borderTopWidth: 1, borderTopColor: '#1c1c1c', marginTop: 20, paddingTop: 18, paddingBottom: 30, paddingHorizontal: 16},
  row: {flexDirection: 'row-reverse', flexWrap: 'wrap', justifyContent: 'center', gap: 16, marginBottom: 10},
  link: {color: '#888', fontSize: 13},
  note: {color: '#555', fontSize: 11, textAlign: 'center', marginTop: 4},
});

// ── FreeBar ───────────────────────────────────────────────────────────────────

// הכותרת התחתונה אומרת את זה, אבל היא נמצאת אחרי כל הקטלוג — כלומר מי
// שנכנס, מצא סרט ולחץ עליו לא הגיע אליה מעולם. מי שקנה את ZOVEX ממישהו
// **אינו מחפש** את ההודעה הזאת: מבחינתו הוא שילם על מוצר תקין, ואין לו
// סיבה לחשוד. לכן זה עולה למעלה, מעל התוכן, במקום שאי אפשר לפספס.
//
// הסרגל יושב מתחת לסרגל העליון ולא גולל איתו, ולכן הוא נראה בכל כניסה
// למסך הבית ובכל מצב — רגיל, קטגוריה, חיפוש ושידורים חיים.
const FREE_BAR_KEY = 'zovex_free_bar_until';
// אותם 30 יום כמו באתר. אפשר לסגור אותו — סרגל שאי אפשר לסגור נקרא
// כרעש ולא כהודעה, והוא חוזר לבד אחרי חודש, כך שגם מי שסגר יראה שוב.
const FREE_BAR_MS = 30 * 24 * 60 * 60 * 1000;

const FreeBar = memo(function FreeBar({onSupport}) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    let live = true;
    AsyncStorage.getItem(FREE_BAR_KEY)
      // ערך פגום או ריק ⇒ מציגים. ברירת המחדל של הודעה כזאת היא להיראות.
      .then(v => { if (live) setShow(!(Number(v) > Date.now())); })
      .catch(() => { if (live) setShow(true); });
    return () => { live = false; };
  }, []);

  const dismiss = useCallback(() => {
    setShow(false);
    AsyncStorage.setItem(FREE_BAR_KEY, String(Date.now() + FREE_BAR_MS))
      .catch(() => {});
  }, []);

  if (!show) return null;
  return (
    <View style={[fbStyles.wrap, {flexDirection: isRTL() ? 'row-reverse' : 'row'}]}>
      <TvFocusable style={fbStyles.main} onPress={onSupport}>
        <Text style={[fbStyles.txt, {textAlign: isRTL() ? 'right' : 'left'}]}
              numberOfLines={2}>
          <Text style={fbStyles.strong}>{t('free.title')}</Text>
          {'  '}
          {t('free.paid')}{' '}
          <Text style={fbStyles.cta}>{t('free.cta')} ›</Text>
        </Text>
      </TvFocusable>
      {/* TvFocusable ולא Pressable: בטלוויזיה סרגל שאי אפשר לסגור מהשלט
          הוא סרגל שנשאר על המסך לנצח. */}
      <TvFocusable style={fbStyles.x} onPress={dismiss}>
        <Text style={fbStyles.xTxt}>✕</Text>
      </TvFocusable>
    </View>
  );
});

const fbStyles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    backgroundColor: 'rgba(229,9,20,0.10)',
    borderTopWidth: 1, borderBottomWidth: 1,
    borderColor: 'rgba(229,9,20,0.35)',
    paddingHorizontal: 12, paddingVertical: 7,
  },
  main: {flex: 1, paddingVertical: 2, paddingHorizontal: 4},
  txt: {color: '#e8e8e8', fontSize: 12, lineHeight: 17},
  strong: {color: '#ff5a63', fontWeight: '900'},
  cta: {color: '#8ab4f8', fontWeight: '700'},
  x: {paddingHorizontal: 8, paddingVertical: 4},
  xTxt: {color: '#888', fontSize: 14, fontWeight: '700'},
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

  // מעבר אחיד בין קרוסלה אוטומטית להחלקה ידנית — שתיהן קוראות לזה, כדי
  // שלא תהיינה שתי אנימציות מעבר שונות תלוי מי הפעיל את המעבר.
  const goToIndex = useCallback(next => {
    Animated.timing(fadeAnim, {toValue: 0, duration: 400, useNativeDriver: true}).start(() => {
      setIndex(next);
      Animated.timing(fadeAnim, {toValue: 1, duration: 400, useNativeDriver: true}).start();
    });
  }, [fadeAnim]);

  // הטיימר מתאפס בכל שינוי index — גם כשהוא עצמו גרם לשינוי, וגם כשההחלקה
  // הידנית למטה גרמה לו. בלי התלות ב-index (setInterval חופשי במקום) החלקה
  // ידנית הייתה "מתחרה" עם הסיבוב האוטומטי שיכול לירות רגע אחרי.
  useEffect(() => {
    if (heroMovies.length < 2) return;
    const t = setTimeout(() => goToIndex((index + 1) % heroMovies.length), 8000);
    return () => clearTimeout(t);
  }, [heroMovies.length, index, goToIndex]);

  // החלקה באצבע — PanResponder מהליבה של RN, בלי ספריית מחוות נוספת.
  // קורא ל-release בלבד, לא עוקב חי אחרי האצבע: כך אין אנימציית-גרירה
  // שנייה שמתחרה עם ה-fade שכבר קיים ב-goToIndex. הסף על dx (לא dy) +
  // דרישה ש-dx יהיה דומיננטי משמעותית מבטיחה שגלילה אנכית של הרשימה
  // שעוטפת את הבאנר לא נחטפת, וש-TvFocusable (לחיצה בלי תזוזה) עובר חופשי.
  const panResponder = useMemo(() => PanResponder.create({
    onMoveShouldSetPanResponder: (_, g) =>
      Math.abs(g.dx) > 14 && Math.abs(g.dx) > Math.abs(g.dy) * 1.5,
    onPanResponderRelease: (_, g) => {
      if (heroMovies.length < 2) return;
      const threshold = Math.min(80, SW * 0.15);
      if (g.dx <= -threshold) goToIndex((index + 1) % heroMovies.length);
      else if (g.dx >= threshold) goToIndex((index - 1 + heroMovies.length) % heroMovies.length);
    },
  }), [heroMovies.length, index, goToIndex]);

  if (heroMovies.length === 0) return null;
  const movie = heroMovies[index % heroMovies.length];

  return (
    <Animated.View style={[styles.hero, {opacity: fadeAnim}]} {...panResponder.panHandlers}>
      {(movie.backdrop_url || movie.thumbnail_url) ? (
        <View style={styles.heroBg}>
          {movie.backdrop_url ? (
            // תמונה רוחבית אמיתית (TMDB backdrop, לא פוסטר) — שכבת cover
            // אחת ונקייה. זה בדיוק מה שהיה חסר וגרם למראה ה"מדבקה": פוסטר
            // צר שנדחס לתוך מסגרת רחבה (ראה ה-fallback למטה). ההסבר המלא
            // ב-add_movie_entry/TMDB_IMG_BACKDROP בשרת.
            <Image
              source={{uri: movie.backdrop_url}}
              style={StyleSheet.absoluteFill}
              resizeMode="cover"
            />
          ) : (
            <>
              {/* נפילה חזרה: תוכן ישן/בלי tmdb_id, עדיין רק עם פוסטר צר.
                  שתי שכבות של אותה תמונה, וזה מכוון.
                  המסגרת בגובה קבוע, ולכן contain לבדו מצייר תמונת פוסטר (צרה
                  וגבוהה) קטנה במרכז בעוד תמונה רוחבית ממלאת את הרוחב — כלומר
                  האריח נראה בגודל אחר לכל פריט בקרוסלה. השכבה המטושטשת ב-cover
                  ממלאת תמיד את המסגרת, וה-contain מעליה מציג את התמונה בשלמותה
                  בלי חיתוך. כך הגודל קבוע והתוכן עדיין שלם. */}
              <Image
                source={{uri: movie.thumbnail_url}}
                style={StyleSheet.absoluteFill}
                resizeMode="cover"
                blurRadius={14}
              />
              <Image
                source={{uri: movie.thumbnail_url}}
                style={StyleSheet.absoluteFill}
                resizeMode="contain"
              />
            </>
          )}
          <DarkGradient />
          <View style={styles.heroContent}>
            {!!movie.year && <Text style={styles.heroYear}>{movie.year}</Text>}
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
        </View>
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
            <TouchableOpacity key={i} onPress={() => goToIndex(i)}
              hitSlop={{top: 10, bottom: 10, left: 6, right: 6}}>
              <View style={[styles.heroDot, i === index && styles.heroDotActive]} />
            </TouchableOpacity>
          ))}
        </View>
      )}
    </Animated.View>
  );
});

// ── helpers ───────────────────────────────────────────────────────────────────

// קטגוריית הסדרה נקבעת לפי *רוב* הפרקים ולא לפי הפרק הראשון שנתקלים בו.
// בקטלוג יש 11 סדרות שבהן פרק בודד מסווג אחרת מכל השאר — למשל 149 פרקים
// של "דרגון בול לעברית" תחת "סדרות" ועוד 4 תחת "אנימה". כשהקטגוריה נלקחה
// מהפרק הראשון (סדר שרירותי), אותה סדרה הופיעה בשתי שורות שונות במסך
// הבית. עכשיו היא נוחתת בשורה אחת בלבד, זו של הרוב.
//
// זה מתקן את התצוגה, לא את הנתונים: הדרך לנקות באמת היא הכפתור «קבע
// קטגוריה לכל הסדרה» שבפאנל.
function buildSeriesMap(movies) {
  const counts = {};      // שם סדרה → {קטגוריה: מספר פרקים}
  const best = {};        // שם סדרה → פרק לדוגמה עם תמונה/תיאור
  movies.forEach(m => {
    const n = m.series_name;
    if (!n) return;
    if (m.category) {
      (counts[n] = counts[n] || {})[m.category] = (counts[n]?.[m.category] || 0) + 1;
    }
    // מעדיפים פרק שיש לו תמונה ותיאור — הראשון לא תמיד מחזיק אותם.
    const cur = best[n];
    const score = (m.thumbnail_url ? 2 : 0) + (m.description ? 1 : 0);
    const curScore = cur ? (cur.thumbnail_url ? 2 : 0) + (cur.description ? 1 : 0) : -1;
    if (score > curScore) best[n] = m;
  });

  const map = {};
  Object.keys(best).forEach(n => {
    const m = best[n];
    const c = counts[n] || {};
    const dominant = Object.keys(c).sort((a, b) => c[b] - c[a])[0] || m.category;
    map[n] = {
      id: 'series_' + n,
      isSeries: true,
      series_name: n,
      name: n,
      title: n,
      thumbnail_url: m.thumbnail_url,
      // כל הפרקים של אותה סדרה חולקים backdrop_url/cast/year — ה-meta
      // ברמת הסדרה נמשך פעם אחת ב-_series_tmdb (ראה השרת), לא לכל פרק.
      backdrop_url: m.backdrop_url,
      cast: m.cast,
      year: m.year,
      description: m.description,
      category: dominant,
    };
  });
  return map;
}

// ── MovieCard ─────────────────────────────────────────────────────────────────

const MovieCard = memo(function MovieCard({item, onPress, hasTVPreferredFocus = false, showProgress = false}) {
  // בטלוויזיה חובה שיהיה סימון ברור לאן ה-focus הגיע — אחרת נראה כאילו השלט
  // "לא עובד". הסימון הזה מצויר עכשיו כולו בצד הנייטיב, ב-TvFocusableView.
  //
  // מה שהיה כאן: useState + onFocusChange, כלומר רינדור מחדש של הכרטיס על
  // כל תזוזת חץ — ובעצם **שני** כרטיסים בכל לחיצה, זה שאיבד וזה שקיבל.
  // זה הרכיב שמצויר יותר מכל אחר באפליקציה, ובטלוויזיה חלשה זה בדיוק מה
  // שהצטבר עד ש"השלט לא הגיב". הפסק דין ויזואלית זהה, בלי שום JS בדרך.
  if (!item || typeof item !== 'object') return null;
  const isLive = !!item.is_live;
  const displayTitle = String(item.name || item.title || '');
  if (!displayTitle) return null;
  const epLabel = (!item.isSeries && item.series_name && item.episode_number)
    ? `עונה ${item.season_number || 1} · פרק ${item.episode_number}` : '';
  const borderColor = isLive ? colors.primary : 'transparent';
  const borderWidth = isLive ? 2 : 0;
  // פס "המשך צפייה" (מהתמונות שדוד הביא). רק כשיש שני המספרים ממש —
  // אין פה ברירת מחדל ל-0%, כי קו אדום בקצה כל כרטיס שאין לו נתון
  // אמיתי הוא בדיוק סוג המצג-שווא שהמפרט אוסר ("אל תמציא נתון").
  const dur = Number(item.duration) || 0;
  const pos = Number(item.position) || 0;
  const progressPct = (showProgress && dur > 0 && pos > 0)
    ? Math.max(2, Math.min(100, (pos / dur) * 100)) : null;
  return (
    // עומק: צל על עטיפה חיצונית, רדיוס+חיתוך על הפנימית. על אותה תצוגה
    // Android מחתך את צל ה-elevation אם overflow:hidden יושב על אותו
    // view — לכן שתי שכבות ולא אחת. בטלוויזיה elevation() מחזיר {} (ראה
    // theme/tokens), כך שהעטיפה כאן חסרת עלות — אפס שינוי להתנהגות
    // המכוונת שתועדה למעלה.
    <View style={[styles.cardShadow, {width: CARD_W}]}>
      <TvFocusable
        style={styles.card}
        onPress={() => onPress(item)}
        hasFocus={hasTVPreferredFocus}>
        <View style={[styles.cardImg, {height: CARD_H, borderColor, borderWidth}]}>
          {item.thumbnail_url ? (
            // [tv_perf] ‎resizeMethod="resize"‎ — נמדד: הפוסטרים הם 500x750
            // ומוצגים ברוחב ~320px בטלוויזיה. בלי זה אנדרואיד מפענח את
            // המקור במלואו, כלומר 1.5MB של bitmap לכרטיס; עם זה הפענוח
            // עצמו יורד לגודל התצוגה — פחות מחצי. עם עשרות כרטיסים
            // מחוברים בו-זמנית זה ההבדל בין לחץ זיכרון לבין שקט.
            <Image source={{uri: item.thumbnail_url}} style={isLive ? styles.cardImgLive : styles.cardImgInner} resizeMode={isLive ? 'contain' : 'cover'} resizeMethod="resize" fadeDuration={200} />
          ) : (
            <View style={styles.noThumb}><Text style={styles.thumbEmoji}>{isLive ? '📡' : '🎬'}</Text></View>
          )}
          {item.isSeries && <View style={styles.badge}><Text style={styles.badgeText}>סדרה</Text></View>}
          {isLive && <View style={[styles.badge, styles.liveBadge]}><Text style={styles.badgeText}>🔴 LIVE</Text></View>}
          {/* פרק בודד — בהורדות, בהמשך צפייה ובמועדפים. השם שלו הוא שם הסדרה,
              ולכן בלי השורה הזו עשרה פרקים שהורדו נראו כעשרה כרטיסים זהים.
              מונח על התמונה ולא מתחת לשם, כדי שגובה הכרטיס לא ישתנה והשורה
              לא תצא עקומה. */}
          {epLabel ? <View style={styles.epBadge}><Text style={styles.epBadgeText} numberOfLines={1}>{epLabel}</Text></View> : null}
          {progressPct != null && (
            <View style={styles.progressTrack}>
              <View style={[styles.progressFill, {width: `${progressPct}%`}]} />
            </View>
          )}
        </View>
        <Text style={styles.cardTitle} numberOfLines={2}>{displayTitle}</Text>
      </TvFocusable>
    </View>
  );
});

// ── NetflixRow ────────────────────────────────────────────────────────────────

const NetflixRow = memo(function NetflixRow({title, items, onPress, isLiveRow, showProgress = false, firstRow = false}) {
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
        // ── למה הערכים שונים בטלוויזיה ──────────────────────────────────
        //
        // דווח: "הסמן לא רץ את כל הדרך בגלילה ימינה, מגיע רק למה שמופיע
        // על המסך". זה לא באג של הסימון אלא של מה שקיים: אנדרואיד מזיז
        // focus רק בין תצוגות **מחוברות**, ו-removeClippedSubviews מנתק
        // מהעץ הנייטיבי כל מה שמחוץ למסך. כשאין יעד מימין, ה-focus נשאר
        // במקום, ולכן גם הגלילה לא קורית — בטלוויזיה הגלילה נגררת אחרי
        // ה-focus, אין אצבע שתגרור אותה.
        //
        // בטלפון זה לא מזיק והחיסכון בזיכרון אמיתי, ולכן ההתנהגות שם לא
        // משתנה בכלל. בטלוויזיה מוותרים על הניתוק ומחזיקים חלון רחב יותר,
        // כך שתמיד יש כרטיס אחד לפחות מעבר לקצה שאפשר לעבור אליו — ומשם
        // ה-ScrollView גולל אליו והרשימה מרנדרת את הבא.
        //
        // ── ולמה הערכים חזרו למטה ────────────────────────────────────────
        //
        // הדבר שתיקן את הבאג הוא removeClippedSubviews בלבד. את החלון
        // הרחבתי "ליתר ביטחון", וזאת הייתה טעות שעלתה ביוקר: windowSize=11
        // הוא חמישה מסכים לכל צד, ועל מסך עם שש עמודות ועשר שורות זה מאות
        // כרטיסים מחוברים בבת אחת, כל אחד עם תמונה. מזה הגיע "אחרי העדכון
        // הכל נתקע".
        //
        // מה שבאמת דרוש ל-focus הוא יעד אחד מעבר לקצה. windowSize=3 נותן
        // מסך שלם לכל צד — יותר מדי ולא פחות מדי — וזה גם הערך שהיה כאן
        // לפני כל הסיפור.
        initialNumToRender={IS_TV ? 7 : 5}
        maxToRenderPerBatch={IS_TV ? 4 : 5}
        updateCellsBatchingPeriod={IS_TV ? 30 : 50}
        windowSize={3}
        removeClippedSubviews={!IS_TV}
        // כל הכרטיסים ברוחב זהה, ולכן אפשר לומר ל-FlatList איפה כל אחד
        // יושב במקום שימדוד. חוסך מדידה אסינכרונית בכל אצווה, וזה בדיוק
        // העומס שמתחרה עם מקשי השלט על אותו thread.
        getItemLayout={(d, i) => ({length: CARD_W + 10,
                                   offset: (CARD_W + 10) * i, index: i})}
        renderItem={({item, index}) => (
          <MovieCard item={item} onPress={onPress}
            hasTVPreferredFocus={IS_TV && firstRow && index === 0}
            showProgress={showProgress} />
        )}
      />
    </View>
  );
});

// ── main component ────────────────────────────────────────────────────────────

export default function HomeScreen({navigation, route}) {
  const [movies, setMovies] = useState([]);
  const [history, setHistory] = useState([]);
  // קבוצת מזהים ולא מערך: הלב על כל כרטיס נבדק בכל ציור, ו-Set נותן בדיקה
  // בזמן קבוע במקום סריקה של כל הרשימה לכל פריט.
  const [favIds, setFavIds] = useState(() => new Set());

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
  // דף חיפוש ייעודי לטלפון בלבד (ראה showSearchScreen למטה, ליד PhoneSearchScreen).
  // בטלוויזיה הסרגל העליון נשאר כפי שהיה.
  const [showSearchScreen, setShowSearchScreen] = useState(false);
  // סינון "חיפוש חכם" בדף החיפוש הייעודי — ז'אנר ושנה, בנוסף לטקסט.
  // 'הכל'/'all' הם ברירת המחדל: בלי סינון, בדיוק כמו היום.
  const [searchFilterCat, setSearchFilterCat] = useState('הכל');
  const [searchFilterYear, setSearchFilterYear] = useState('all');
  useEffect(() => {
    if (searchTyping) {
      const t = setTimeout(() => searchRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
  }, [searchTyping]);
  const [user, setUser] = useState(null);

  // החלפת מועדף. מוגדר כאן ולא למעלה כי הוא תלוי ב-user, ובקובץ הזה user
  // מוגדר רק בשורה הזו — שימוש בו קודם היה נופל על TDZ.
  // עדכון אופטימי: הלב מתמלא מיד ומתבטל רק אם השרת נכשל. בלי זה הלב "נתקע"
  // עד שהרשת עונה, וזה מרגיש שבור בחיבור איטי.
  const toggleFavorite = useCallback(async item => {
    const uid = user?.id;
    if (!uid || !item?.id) return;
    const id = String(item.id);
    const had = favIds.has(id);
    const flip = add => setFavIds(prev => {
      const next = new Set(prev);
      if (add) next.add(id); else next.delete(id);
      return next;
    });
    flip(!had);
    const ok = had ? await removeFavorite(id, uid) : await addFavorite(item, uid);
    if (!ok) flip(had);            // החזרה למצב הקודם
  }, [favIds, user]);

  // הסרת פריט בודד מ"המשך צפייה"/היסטוריה. אותה תבנית כמו המועדפים:
  // מורידים מהמסך מיד, ואם השרת נכשל — מחזירים את הפריט ומודיעים, במקום
  // להעמיד פנים שנמחק. גם מנקים את ה-progress כדי שלא יישאר מיקום שמור
  // (best-effort; ההצלחה נקבעת לפי הסרה מההיסטוריה עצמה).
  const handleRemoveFromHistory = useCallback(async item => {
    const uid = user?.id;
    const id = item?.media_id != null ? String(item.media_id)
             : item?.id != null ? String(item.id) : '';
    if (!uid || !id) return;
    let prev;
    setHistory(cur => { prev = cur; return cur.filter(h => String(h.media_id) !== id); });
    removeProgress(id, uid);       // best-effort, לא חוסם
    const ok = await removeFromHistory(id, uid);
    if (!ok && prev) {
      setHistory(prev);            // החזרה למצב הקודם
      Alert.alert('ההסרה נכשלה', 'לא הצלחנו להסיר את הפריט. נסה שוב.');
    }
  }, [user]);

  const handleClearHistory = useCallback(() => {
    const uid = user?.id;
    if (!uid) return;
    Alert.alert('ניקוי היסטוריה',
      'להסיר את כל פריטי ההיסטוריה? התוכן עצמו יישאר בקטלוג.',
      [{text: 'ביטול', style: 'cancel'},
       {text: 'נקה', style: 'destructive', onPress: async () => {
          let prev;
          setHistory(cur => { prev = cur; return []; });
          const ok = await clearHistory(uid);
          if (!ok && prev) {
            setHistory(prev);
            Alert.alert('הניקוי נכשל', 'לא הצלחנו לנקות את ההיסטוריה. נסה שוב.');
          }
       }}]);
  }, [user]);
  const [showSignIn, setShowSignIn] = useState(false);
  const [showCatModal, setShowCatModal] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  // סימון focus לפקדי הסרגל העליון בטלוויזיה (בטלפון נשאר תמיד false)
  // ארבעת מצבי ה-focus של פקדי הסרגל הוסרו. הם ישבו ב-state של מסך הבית
  // כולו, ולכן כל תזוזת חץ אל כפתור בסרגל או ממנו רינדרה מחדש את **כל**
  // המסך — כל השורות, כל הכרטיסים. הטבעת הלבנה מצוירת עכשיו בנייטיב,
  // ב-TvFocusableView, ולכן אין למי לספר על זה.
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
    const favP = loggedInUser ? fetchFavoriteIds(loggedInUser.id)
                              : Promise.resolve(new Set());
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
      setFavIds(await favP);
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
  //
  // אבל שתי הדרכים האלה מגיבות רק לחזרה מהרקע. מחיקה בפאנל בזמן שהאפליקציה
  // *פתוחה על המסך* לא הגיעה לצופה בכלל — לא "בדיליי", אלא בלי גבול, כי אין
  // שום דבר שמושך מחדש. וגם בחזרה מהרקע, מטמון של חמש דקות עוד יכול להחזיר
  // את הרשימה הישנה.
  //
  // לכן: שואלים את מונה גרסת התוכן (~25 בתים) — בחזרה מהרקע וגם כל דקה בזמן
  // שהמסך פתוח — ומושכים קטלוג מחדש רק כשהמספר זז. אם הנקודה עוד לא קיימת
  // בשרת, isCatalogStale מחזירה false וההתנהגות זהה לקודם.
  // בכוונה לא load(true): הוא מאפס את _hydratedRef ולכן חוזר למסלול הדו-שלבי,
  // שמציב קודם 800 פריטים בלבד — כלומר הרשימה מתכווצת מול העיניים של מי
  // שגולל כרגע — וגם מדליק את חיווי הריענון בלי שביקשו. כאן מחליפים את
  // הקטלוג במקום, בלי הבהוב.
  const syncIfChanged = useCallback(async () => {
    try {
      if (!(await isCatalogStale())) return;
      clearCache();
      const full = await fetchMovies();
      if (full && full.length) setMovies(full);
    } catch {}
  }, []);

  useEffect(() => {
    const sub = AppState.addEventListener('change', state => {
      if (state === 'active') { load(false, user); syncIfChanged(); }
    });
    return () => sub.remove();
  }, [load, user, syncIfChanged]);

  useEffect(() => {
    const id = setInterval(() => {
      if (AppState.currentState === 'active') syncIfChanged();
    }, CATALOG_POLL_MS);
    return () => clearInterval(id);
  }, [syncIfChanged]);

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
      syncIfChanged();
    });
    return unsub;
  }, [navigation, syncIfChanged]);

  const seriesMap = useMemo(() => buildSeriesMap(movies), [movies]);

  const liveChannels = useMemo(() => movies.filter(m => m.is_live), [movies]);

  const allCategories = useMemo(() => {
    const cats = [...new Set(movies.filter(m => !m.is_live).map(m => m.category).filter(Boolean))];
    const tabs = ['הכל'];
    if (liveChannels.length > 0) tabs.push('שידורים חיים');
    tabs.push(...cats);
    tabs.push(DOWNLOADS_CATEGORY);
    tabs.push('מועדפים');
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
    if (cat === 'מועדפים') {
      if (!Array.isArray(movies)) return [];
      return movies.filter(m => m && favIds.has(String(m.id)));
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
      // הקטגוריה שנבדקת לפרק היא זו של *הסדרה* (קטגוריית הרוב) ולא של הפרק
      // עצמו. בלי זה פרק בודד שסווג אחרת גורר את כל הסדרה לשורה נוספת —
      // וזה בדיוק מה שהופיע במסך הבית: אותה סדרה גם ב"סדרות" וגם ב"אנימה".
      const effCat = seriesName && seriesMap && seriesMap[seriesName]
        ? seriesMap[seriesName].category : m.category;
      if (!hit || (cat !== 'הכל' && effCat !== cat)) return;
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
  }, [movies, liveChannels, history, favIds, seriesMap, matchItem, qTokens, downloads]);

  const netflixRows = useMemo(() => {
    // בזמן חיפוש המסך מציג רשת תוצאות, לא את השורות האלה. בלי היציאה
    // המוקדמת הן חושבו מחדש בכל הקשה — עשרות קטגוריות × כל הקטלוג — בלי
    // שאף אחד רואה אותן.
    if (qTokens.length) return [];
    const rows = [];
    if (liveChannels.length > 0)
      rows.push({title: t('common.live'), isLiveRow: true, items: liveChannels});
    // /api/history כבר מצרף position/duration לכל שורה (ראה fix_history_resume
    // בשרת) — אבל movies.find מחזיר את פריט ה**קטלוג** הנקי, בלי השדות האלה.
    // בלעדי המיזוג כאן פס ההתקדמות תמיד null, כי שום מקום אחר לא מחזיק את
    // שני המספרים יחד. עותק חדש ולא מוטציה על movies[i] — אותו פריט קטלוג
    // מוצג גם בשורות אחרות (למשל "הכל"), בלי פס התקדמות שם.
    const histItems = history.map(h => {
      const m = movies.find(x => x.id === h.media_id);
      return m ? {...m, position: h.position, duration: h.duration} : null;
    }).filter(Boolean);
    if (histItems.length > 0)
      rows.push({title: t('home.continueWatching'), items: histItems, showProgress: true});
    const favItems = movies.filter(m => m && favIds.has(String(m.id)));
    if (favItems.length > 0) rows.push({title: t('home.myFavorites'), items: favItems});
    allCategories
      .filter(c => c !== 'הכל' && c !== 'שידורים חיים' && c !== 'היסטוריה'
                && c !== 'מועדפים' && c !== DOWNLOADS_CATEGORY)
      .forEach(cat => {
        const items = getItemsForCategory(cat);
        // הכותרת מתורגמת לתצוגה; cat עצמו נשאר בעברית כי הוא גם המפתח
        // שלפיו מסננים.
        if (items.length > 0) rows.push({title: catName(cat), items});
      });
    return rows;
  }, [liveChannels, history, movies, favIds, allCategories, getItemsForCategory, qTokens]);

  // ── שידורים חיים: שורה לכל ז'אנר, כמו באתר ────────────────────────────
  // עד עכשיו כל 103 הערוצים נשפכו לרשת אחת ארוכה, ולמצוא בה ערוץ מסוים היה
  // גלילה עיוורת. אין שדה ז'אנר בנתונים, אז הוא נגזר מהשם (ראה
  // utils/liveGenres.js — אותם כללים בדיוק שבאתר).
  //
  // getItemsForCategory ולא liveChannels הגולמי: הוא כבר מסנן לפי החיפוש,
  // ולכן הקלדה בתיבה מצמצמת גם כאן, שורה-שורה, במקום להראות הכל.
  const liveGenreRows = useMemo(() => {
    if (category !== 'שידורים חיים') return [];
    return groupLiveByGenre(getItemsForCategory('שידורים חיים'))
      // g.title הוא גם מפתח הקיבוץ — מתרגמים רק לתצוגה.
      .map(g => ({title: genreName(g.title), items: g.items, isLiveRow: true}));
  }, [category, getItemsForCategory]);

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
      // דף החיפוש הייעודי (טלפון בלבד) הוא View רגיל ולא Modal — בכוונה,
      // כדי שלא ייווצר שוב Modal-בתוך-Modal כשפותחים פריט מתוך תוצאות
      // החיפוש (ראה ההסבר ליד seasonPickerWrap). בלי שורה זו "אחורה" היה
      // מדלג ישר על הדף הזה אל ניקוי החיפוש/שינוי הקטגוריה.
      if (showSearchScreen) {
        setShowSearchScreen(false); clearSearch();
        setSearchFilterCat('הכל'); setSearchFilterYear('all');
        return true;
      }
      if (showCatModal) { setShowCatModal(false); return true; }
      if (showUserMenu) { setShowUserMenu(false); return true; }
      if (showSupport) { setShowSupport(false); return true; }
      // [tv_keyboard] יציאה ממצב הקלדה קודמת לניקוי החיפוש.
      // זהו הצעד שמחליף את ה-onBlur שהיה מכבה את מצב ההקלדה מעצמו (ראה
      // ההסבר ליד searchTyping): כל עוד המקלדת פתוחה, "אחורה" סוגר אותה,
      // ורק לחיצה נוספת מנקה את מה שהוקלד.
      if (searchTyping) { setSearchTyping(false); return true; }
      if (search) { clearSearch(); return true; }
      if (category !== 'הכל') { setCategory('הכל'); return true; }
      // אין יותר מה לסגור — כאן אנדרואיד סוגר את האפליקציה. בטלוויזיה זה קורה
      // בלחיצה אחת על השלט, בלי שום אזהרה, ולכן צופים נזרקו החוצה באמצע. שואלים
      // קודם. בטלפון משאירים את התנהגות ה"אחורה" הרגילה שמשתמשים מצפים לה.
      if (IS_TV) { setShowExit(true); return true; }
      return false;
    };
    const sub = BackHandler.addEventListener('hardwareBackPress', onBack);
    return () => sub.remove();
  }, [isFocused, showDonation, detailItem, liveChannel, showCatModal, showUserMenu, showSupport, search, searchTyping, category, showExit, showSearchScreen]);

  // יציב, כי FreeBar עטוף ב-memo: פונקציה חדשה בכל רינדור הייתה מבטלת
  // את ה-memo ומצייר את הסרגל מחדש בכל לחיצה ובכל שינוי חיפוש.
  const openSupport = useCallback(() => setShowSupport(true), []);

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

  // מסך ההגדרות שולח לכאן openSupport אחרי שהמשתמש קרא שהאפליקציה
  // חינמית ורוצה לומר שגבו ממנו כסף. הפרמטר מנוקה מיד אחרי השימוש,
  // אחרת חזרה למסך הבית הייתה פותחת את התמיכה שוב ושוב.
  useEffect(() => {
    if (!route?.params?.openSupport) return;
    setShowSupport(true);
    navigation.setParams({openSupport: undefined});
  }, [route?.params?.openSupport, navigation]);

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
      // רשימת הפרקים של הסדרה, בסדר צפייה ובכל העונות, כדי שהנגן יידע מה
      // "הפרק הבא". הנגן מציג את כרטיס הפרק הבא ועובר אליו לבד רק כשהוא
      // מקבל אותה — ורק מסך הסדרה הישן העביר אותה. מכאן, שהוא הדרך שבה
      // חלון הפרטים מנגן, היא לא עברה: פרק נגמר ולא היה לא כפתור ולא מעבר.
      // בכל העונות, כך שעונה 1 פרק אחרון ממשיך לעונה 2 פרק 1.
      const eps = item.series_name && Array.isArray(movies)
        ? movies
            .filter(m => m && !m.is_live && m.series_name === item.series_name)
            .sort((a, b) => ((a.season_number || 1) - (b.season_number || 1))
                         || ((a.episode_number || 0) - (b.episode_number || 0)))
        : null;
      navigation.navigate('Player', {
        movie: item, startTime: 0, userId,
        seriesEpisodes: eps && eps.length > 1 ? eps : null,
      });
    }
  }, [navigation, user, movies]);

  const handleHeroPlay = useCallback(movie => {
    const d = movie.series_name ? {...seriesMap[movie.series_name], thumbnail_url: movie.thumbnail_url, description: movie.description} : movie;
    showDonationModal(() => setDetailItem(d));
  }, [seriesMap, showDonationModal]);

  const handleHeroInfo = useCallback(movie => {
    const d = movie.series_name ? {...seriesMap[movie.series_name], thumbnail_url: movie.thumbnail_url, description: movie.description} : movie;
    showDonationModal(() => setDetailItem(d));
  }, [seriesMap, showDonationModal]);

  // כניסה נסתרת לפאנל ההעלאה: מקלידים את קוד הגישה בשדה החיפוש.
  // הקוד עצמו *אינו* כאן אלא בשרת. APK הוא קובץ ZIP, ו-`strings` מוציא ממנו
  // כל מחרוזת בשניות — קוד ששמור באפליקציה שקול לקוד פומבי, וזה לא מספיק
  // לפאנל שדוחף קבצים לחשבון הטלגרם הפרטי.
  // נשלח לשרת רק מה שנראה כמו מועמד (מילה אחת, 12 תווים ומעלה) ורק אחרי
  // שההקלדה נחה, כדי לא לשלוח בקשה על כל תו שמקלידים בחיפוש רגיל.
  const codeTimer = useRef(null);
  useEffect(() => () => clearTimeout(codeTimer.current), []);

  const tryPanelCode = useCallback(v => {
    clearTimeout(codeTimer.current);
    const c = (v || '').trim();
    if (c.length < 12 || /\s/.test(c)) return;
    codeTimer.current = setTimeout(async () => {
      try {
        const d = await verifyPanelCode(c);
        if (!d || !d.ok) return;
        clearSearch();
        // maxSize מגיע מהשרת לפי סוג חשבון הטלגרם (2GB רגיל, 4GB Premium),
        // כדי שהפאנל יוכל לומר מראש שקובץ גדול מדי במקום להעלות אותו לחינם.
        navigation.navigate('SavedUpload', {
          code: c, account: d.account,
          maxSize: d.max_size || 0, freeDisk: d.free_disk || 0,
          // השרת מחזיר ready ו-reason מאז ומתמיד, ואנחנו התעלמנו מהם:
          // הפאנל נפתח כרגיל, המשתמש בחר קובץ וחיכה, ורק אז קיבל 503.
          // עכשיו המסך אומר את זה לפני הבחירה. reason חדש בשרת, ולכן
          // ברירת המחדל היא ready — שרת ישן אינו נחסם.
          ready: d.ready !== false, reason: d.reason || '',
        });
      } catch (_) {
        // קוד שגוי — בשקט ובכוונה. הודעת שגיאה הייתה מסגירה שיש כאן פאנל.
      }
    }, 700);
  }, [navigation]);

  // [tv_perf] בטלוויזיה תיבת החיפוש אינה מבוקרת (ראה ההסבר ליד ה-TextInput),
  // ולכן ניקוי מ-JS חייב לנקות גם את הטקסט הנייטיב — אחרת ה-state מתרוקן
  // והאות נשארת על המסך.
  const clearSearch = useCallback(() => {
    setSearch('');
    if (IS_TV) searchRef.current?.clear();
  }, []);

  const handleSearchChange = useCallback(v => {
    setSearch(v);
    if (!v) setCategory('הכל');
    tryPanelCode(v);
  }, [tryPanelCode]);

  const onSearchFocus = useCallback(() => {
    Animated.timing(searchAnim, {toValue: 1, duration: 220, useNativeDriver: false}).start();
  }, [searchAnim]);

  const onSearchBlur = useCallback(() => {
    Animated.timing(searchAnim, {toValue: 0, duration: 220, useNativeDriver: false}).start();
  }, [searchAnim]);

  const searchBorderColor = searchAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ['rgba(255,255,255,0.08)', colors.primary],
  });

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
                  showProgress={row.showProgress}
                  onPress={handleItemPress} firstRow={index === 0} />
    ),
    [handleItemPress],
  );
  const renderGridItem = useCallback(
    ({item, index}) => (
      <MovieCard item={item} onPress={handleItemPress}
        // [tv_perf] לא מבקשים focus התחלתי בזמן הקלדה. רשימת התוצאות
        // מתחלפת בכל אות, הכרטיס הראשון הוא תצוגה חדשה, ובקשת focus
        // ממנו לוקחת את הסמן מתיבת החיפוש וסוגרת את המקלדת. הצד הנייטיב
        // חוסם את זה בכל מקרה; כאן זה נאמר במפורש גם ב-JS.
        hasTVPreferredFocus={IS_TV && index === 0 && !searchTyping} />
    ),
    [handleItemPress, searchTyping],
  );

  // ── מצב התצוגה ו-gridItems ──────────────────────────────────────────────
  //
  // כאן, ו**לפני** היציאות המוקדמות שמתחת, כי ‎gridItems‎ הוא ‎useMemo‎.
  //
  // הבאג שזה תיקן, ושאני גרמתי לו: קודם זה היה חישוב רגיל אחרי
  // ‎if (loading) return‎, וזה חוקי לגמרי. ברגע שהפכתי אותו ל-‎useMemo‎ הוא
  // הפך להוק שרץ **רק כשהטעינה נגמרה** — כלומר מספר ההוקים השתנה בין
  // רינדור לרינדור, React זרק "Rendered more hooks than during the
  // previous render", והאפליקציה נתקעה על מסך שחור לפני שהפתיח בכלל רץ.
  //
  // הכלל: הוק לעולם לא אחרי ‎return‎ מוקדם.
  const isNetflixMode = category === 'הכל' && !query;
  // השידורים החיים מוצגים בשורות ז'אנר ולא ברשת — ולכן גם הם לא צריכים
  // gridItems. בלי התנאי הזה הרשימה הייתה מחושבת ונזרקת בכל רינדור.
  const isLiveMode = category === 'שידורים חיים';
  // [tv_perf] ‎useMemo‎ ולא חישוב בגוף הרינדור.
  //
  // נמדד על הקטלוג האמיתי (18,078 פריטים): סריקה אחת של הרשימה עם בניית
  // האובייקטים לוקחת 3.3ms במכונת פיתוח, כלומר כ-26ms בקופסת טלוויזיה.
  // בגוף הרינדור זה נגבה **בכל** רינדור מחדש — כל הקלדה, כל פתיחת מודאל,
  // כל אנימציה — גם כשהקטגוריה והחיפוש לא השתנו כלל.
  //
  // ‎getItemsForCategory‎ הוא ‎useCallback‎ שתלוי ב-movies, favIds, history,
  // downloads, qTokens, seriesMap ו-liveChannels, ולכן הזהות שלו היא כבר
  // מפתח שלם: כשמשהו מהם משתנה החישוב חוזר, וכשלא — לא.
  const gridItems = useMemo(
    () => (isNetflixMode || isLiveMode ? [] : getItemsForCategory(category)),
    [isNetflixMode, isLiveMode, category, getItemsForCategory]);

  // צ'יפים לסינון ז'אנר בדף החיפוש — תת-קבוצה של allCategories, בלי
  // הטאבים שהם לא באמת "ז'אנר" (מועדפים/היסטוריה/הורדות הן רשימות
  // אישיות של המשתמש, לא סיווג תוכן; "הכל" מיוצג ע"י הצ'יפ הראשון שלנו).
  const searchGenreOptions = useMemo(
    () => allCategories.filter(c =>
      c !== 'הכל' && c !== DOWNLOADS_CATEGORY && c !== 'מועדפים' && c !== 'היסטוריה'),
    [allCategories]);

  // דלי שנים פשוטים ולא טווח חופשי: רוב התוכן הישן בקטלוג כלל לא הגיע
  // דרך TMDB (נבדק על המדגם החי — כ-2/3 מהפריטים בלי year כלל), ובורר
  // שנה מדויקת היה מרגיש "שבור" לרוב הקטלוג. 'all' לא מסנן כלום — פריט
  // בלי year עדיין מופיע ב"הכל", רק לא בדלי שנה ספציפי.
  const matchesYearFilter = useCallback(item => {
    if (searchFilterYear === 'all') return true;
    const y = parseInt(item?.year, 10);
    if (!y) return false;
    if (searchFilterYear === '2020') return y >= 2020;
    if (searchFilterYear === '2010') return y >= 2010 && y <= 2019;
    if (searchFilterYear === '2000') return y >= 2000 && y <= 2009;
    if (searchFilterYear === 'old') return y < 2000;
    return true;
  }, [searchFilterYear]);

  // דף החיפוש הייעודי (טלפון): ברירת המחדל "הכל"/"all" מחפשת בלי קשר
  // לקטגוריה שנבחרה במסך הבית מתחתיו — "חיפוש נקי" ולא המשך חיפוש-תוך-
  // קטגוריה. צ'יפי הז'אנר/שנה מצמצמים מעל זה, לא מחליפים את הטקסט.
  // חסם ל-showSearchScreen כדי לא לחשב את זה בכל הקשה כשהדף סגור.
  const searchScreenItems = useMemo(() => {
    if (!showSearchScreen) return [];
    const base = getItemsForCategory(searchFilterCat);
    return searchFilterYear === 'all' ? base : base.filter(matchesYearFilter);
  }, [showSearchScreen, getItemsForCategory, searchFilterCat, searchFilterYear, matchesYearFilter]);

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
        <ActivityIndicator size="large" color={colors.primary} />
        <Text style={styles.loadingText}>טוען...</Text>
      </View>
    );
  }

  // משותף לטלוויזיה (שורה שטוחה בסרגל) ולטלפון (מקובץ עם כפתור החיפוש,
  // ראה למטה) — בלי שינוי בהתנהגות, רק מקום אחד להגדיר אותו.
  const UserAvatarBtn = user ? (
    <TvFocusable
      onPress={() => setShowUserMenu(true)}
      style={styles.userBtn}>
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
      style={styles.signInBtn}>
      <Text style={styles.signInTxt}>כניסה</Text>
    </TvFocusable>
  );

  const TopBar = (
    <View style={styles.topBar}>
      <Text style={styles.appTitle}>ZOVEX</Text>

      {IS_TV ? (
        <>
          {/* תיבת הטקסט עצמה לא מקבלת focus מה-D-pad (אחרת השלט נתקע בתוכה);
              במקום זה המרובע נעצר על העטיפה, ולחיצה מרכזית מעבירה את
              ה-focus פנימה ופותחת את המקלדת. */}
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
                // [tv_perf] בטלוויזיה **לא מבוקרת**.
                //
                // ‎value={search}‎ אומר: בכל תו, RN מחזיר את הטקסט הנייטיב למה
                // ש-JS מחזיק. כשה-thread של JS עסוק — ובטלוויזיה הוא עסוק,
                // כי כל הקלדה מפעילה סינון של הקטלוג ורינדור מחדש — הערך
                // שחוזר הוא הערך הישן, והאות שהוקלדה בינתיים נמחקת.
                // דווח מהשטח: "רק אות אחת".
                //
                // עם ‎defaultValue‎ הטקסט הנייטיב הוא מקור האמת בזמן הקלדה,
                // ו-JS רק מאזין. ניקוי מ-JS עובר דרך ‎clearSearch‎, שקורא
                // ל-‎clear()‎ על התיבה עצמה.
                defaultValue=""
                onChangeText={handleSearchChange}
                onFocus={onSearchFocus}
                // [tv_keyboard] מצב ההקלדה **אינו** נכבה כאן.
                //
                // דווח: "מקליד מילה אחת ואז צריך לסגור את המקלדת ולפתוח מחדש".
                // זו הייתה השורה. המקלדת של אנדרואיד TV היא חלון נפרד שלוקח
                // את ה-focus, ולכן היא מפיקה onBlur על התיבה תוך כדי הקלדה.
                // כיבוי מצב ההקלדה שם מחזיר descendantFocusability ל-
                // FOCUS_BLOCK_DESCENDANTS, ואנדרואיד **מנקה focus מילד ממוקד**
                // ברגע שחוסמים — כלומר התיבה איבדה focus, ה-IME נסגר, והדרך
                // היחידה חזרה הייתה לחיצה מרכזית נוספת. בדיוק מה שדווח.
                //
                // היציאה ממצב הקלדה נעשית עכשיו רק לפי כוונה מפורשת של
                // המשתמש: "אישור" במקלדת, או "אחורה" (ראה מטפל ה-Back).
                onBlur={() => { onSearchBlur && onSearchBlur(); }}
                onSubmitEditing={() => setSearchTyping(false)}
                returnKeyType="search"
                blurOnSubmit
                textAlign="right"
              />
            </Animated.View>
          </TvFocusable>

          {/* כפתור התמיכה יושב כאן ולא כבועה צפה.
              הבועה היא View ממוקם מוחלט מעל הרשת, ומנוע ה-focus של אנדרואיד
              בוחר את היעד הבא גאומטרית — הרשת בולעת כל לחיצה על ה-D-pad
              והכפתור לא נבחר לעולם. דוד: "לא הצלחתי להגיע אליו בשום צורה".
              כתבתי שם בהערה שהוא "נשאר נגיש בניווט", וזו הייתה הנחה שלי שלא
              נבדקה. בסרגל העליון הוא חלק מהזרימה: חץ למעלה מהשורה הראשונה
              מגיע לכאן, וימינה/שמאלה עובר בין חיפוש, תמיכה ומשתמש. */}
          <TvFocusable
            onPress={() => setShowSupport(true)}
            style={styles.tvSupportBtn}>
            <Text style={styles.tvSupportTxt}>➤ {t('home.support')}</Text>
          </TvFocusable>

          {UserAvatarBtn}
        </>
      ) : (
        // בטלפון: לא תיבת טקסט בסרגל העליון, אלא כפתור חיפוש שפותח דף
        // חיפוש ייעודי במסך מלא (ראה PhoneSearchScreen למטה). דווח מדוד:
        // "תוסיפי... ככה החיפוש יותר טוב יותר יפה". מקובץ עם האווטאר כדי
        // שהשני יישבו יחד בקצה הסרגל, כמו שרגיל באפליקציות סטרימינג.
        <View style={styles.topBarRightGroup}>
          <TvFocusable
            style={styles.searchIconBtn}
            onPress={() => setShowSearchScreen(true)}>
            <Image source={NAV_SEARCH} style={styles.topIcon} />
          </TvFocusable>
          {UserAvatarBtn}
        </View>
      )}
    </View>
  );

  // ── סרגל ניווט צף תחתון ──────────────────────────────────────────────
  //
  // דוד הביא צילומים מ-Netflix וביקש את זה בדיוק — עם הבדל אחד מכוון:
  // אצלנו השם נשאר מתחת לכל כרטיס. "הבעיה של נטפליקס לא רושם את השמות,
  // אנחנו כן צריכים" — ה-cardTitle לא נגע בכלל.
  //
  // טלפון/טאבלט בלבד. בטלוויזיה אין "מגע" לסרגל צף לנגוע בו, והניווט
  // כבר קיים ועובד דרך TopBar + השלט — בדיוק כמו שהבועה הצפה של
  // טלגרם כבר מוגבלת לטלפון, באותו נימוק.
  //
  // כל כפתור קורא לפעולה שכבר קיימת ונבדקה במקום אחר במסך הזה — "בית"
  // ו"מועדפים" הם אותה קריאה בדיוק כמו ב-CatModal, "חיפוש" ממקד את
  // אותה תיבת טקסט שב-TopBar, ו"שלי" הוא בדיוק מה שכפתור האווטאר למעלה
  // כבר עושה. שום לוגיקת ניווט חדשה לא נוספה כאן.
  const isHomeActive = category === 'הכל' && !search;
  const isFavActive = category === 'מועדפים';
  const BottomNav = !IS_TV && (
    // סרגל שטוח ברוחב מלא עם קו עליון דק — כמו נטפליקס. הגרסה הקודמת
    // (גלולה צפה + צל elevation 14 + זוהר על האייקון הפעיל) היא מה שנראה
    // "תלת מימד". פעיל = אייקון מלא ולבן; לא פעיל = קו דק באפור.
    <View style={styles.bottomNavWrap} pointerEvents="box-none">
      <View style={styles.bottomNav}>
        <TvFocusable style={styles.bottomNavItem}
          onPress={() => { setCategory('הכל'); clearSearch(); }}>
          <Image source={isHomeActive ? NAV_HOME_ON : NAV_HOME}
            style={[styles.bottomNavIcon, isHomeActive && styles.bottomNavIconActive]} />
          <Text style={[styles.bottomNavLabel, isHomeActive && styles.bottomNavLabelActive]}>בית</Text>
        </TvFocusable>
        <TvFocusable style={styles.bottomNavItem}
          onPress={() => setShowSearchScreen(true)}>
          <Image source={NAV_SEARCH} style={styles.bottomNavIcon} />
          <Text style={styles.bottomNavLabel}>חיפוש</Text>
        </TvFocusable>
        <TvFocusable style={styles.bottomNavItem}
          onPress={() => { setCategory('מועדפים'); clearSearch(); }}>
          <Image source={isFavActive ? NAV_HEART_ON : NAV_HEART}
            style={[styles.bottomNavIcon, isFavActive && styles.bottomNavIconActive]} />
          <Text style={[styles.bottomNavLabel, isFavActive && styles.bottomNavLabelActive]}>מועדפים</Text>
        </TvFocusable>
        <TvFocusable style={styles.bottomNavItem}
          onPress={() => (user ? setShowUserMenu(true) : startSignIn())}>
          {user && user.picture ? (
            <Image source={{uri: user.picture}} style={styles.bottomNavAvatar} />
          ) : (
            <Image source={NAV_USER} style={styles.bottomNavIcon} />
          )}
          <Text style={styles.bottomNavLabel}>שלי</Text>
        </TvFocusable>
      </View>
    </View>
  );

  const CatsButton = (
    <View style={styles.catsRow}>
      {category !== 'הכל' && (
        <TvFocusable
          onPress={() => { setCategory('הכל'); clearSearch(); }}
          style={styles.activeCatChip}>
          <Text style={styles.activeCatChipTxt}>✕  {category}</Text>
        </TvFocusable>
      )}
      <TvFocusable
        onPress={() => setShowCatModal(true)}
        style={styles.catsModalBtn}>
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
              onPress={() => { setCategory(c); clearSearch(); setShowCatModal(false); }}
              style={styles.catOverlayItem}
              activeOpacity={0.65}>
              <Text style={[styles.catOverlayText, category === c && styles.catOverlayTextActive]}>
                {catName(c)}
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
      {/* בטלפון השכבה סוגרת בלחיצה מחוץ לתפריט. בטלוויזיה היא View רגיל:
          TouchableOpacity שמכסה מסך מלא הוא עוד יעד focus אפשרי שיכול
          לבלוע את ה-D-pad, ואין בו צורך — יציאה היא כפתור Back, שכבר
          מטופל. */}
      <OverlayWrap
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
 
