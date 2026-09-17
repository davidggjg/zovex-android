// מתאם drop-in: אותו API של react-native-video, מנוע של libVLC.
//
// למה בכלל: react-native-video רץ על ExoPlayer, שמסתמך על המפענחים של
// **המכשיר**. ממירי Android TV בדרך כלל חסרים רישיון ל-AC-3/E-AC-3 (Dolby),
// ואז ExoPlayer זורק את רצועת הקול **בשקט** — וידאו מנגן, אין סאונד, אין
// שגיאה (נמדד: 16 מתוך 16 פרקי ונסדיי). אותו שורש בדיוק ב-AVI, שבו הוא
// נכשל לגמרי. libVLC נושאת מפענחים משלה (מבוססי FFmpeg) ולכן מנגנת AC-3,
// E-AC-3, DTS, AVI ו-MKV בלי להסתמך על המכשיר — וגם סובלנית לשידורי IPTV
// שבורים. זה מה שמכבה מקור שלם של באגים במקום לטפל בכל פורמט בשרת.
//
// הרישיון: libVLC היא LGPL-2.1+, ובאנדרואיד היא מגיעה כ-.so — קישור דינמי,
// שמקיים את דרישת ה-LGPL. אין שום חובה לפתוח את הקוד של האפליקציה. מה
// שאסור זה להעתיק קוד מ**אפליקציית** VLC (שהיא GPL), ואנחנו לא עושים זאת.
//
// הייבוא הוא ישירות מ-VLCPlayer ולא מהחבילה: ה-index שלה גורר גם את
// playerView, שמייבא react-native-slider (נזנח) ו-react-native-vector-icons.
// אנחנו צריכים רק את משטח הווידאו, ולכן עוקפים אותם לגמרי.
//
// שתי מלכודות שה-README שלהם מתעד לא נכון, ושבגללן המתאם הזה קיים:
//
//   1. seek הוא **שבר בין 0 ל-1**, לא שניות.
//   2. ה-README אומר ש-currentTime/duration הם "בשניות" — וזה שגוי.
//      הדוגמה שלהם עצמה מוכיחה מילישניות:
//        {currentTime: 30154, duration: 99750, position: 0.30}
//      ו-30154/99750 = 0.302. כלומר מילישניות.
//
// כל ההמרות יושבות כאן, במקום אחד, כך ששני הנגנים (טלפון וטלוויזיה) לא
// יודעים עליהן כלום וממשיכים לעבוד ביחידות שהם מכירים — שניות.
import React, {forwardRef, useCallback, useImperativeHandle, useRef} from 'react';
import {StyleSheet} from 'react-native';
import VLCPlayer from 'react-native-vlc-media-player/VLCPlayer';

// caching של הרשת: הכתובות שלנו נמשכות מטלגרם דרך השרת, ונמדד ש-window
// חוזר תוך שנייה-שתיים או נזנח. מרווח של 3 שניות נותן לבאפר לעמוד בעיכוב
// בלי להאריך יותר מדי את ההתחלה.
const DEFAULT_INIT_OPTIONS = ['--network-caching=3000'];

const VlcVideo = forwardRef(function VlcVideo(props, fwdRef) {
  const {
    source,
    style,
    paused,
    rate,
    resizeMode,
    onLoad,
    onProgress,
    onEnd,
    onError,
    // props של ExoPlayer בלבד. מתקבלים ונזרקים בכוונה, כדי שהנגנים לא
    // יצטרכו להשתנות ושלא ייווצר prop לא מוכר על הרכיב הנייטיבי.
    controls: _controls,
    bufferConfig: _bufferConfig,
    progressUpdateInterval: _pui,
    ...rest
  } = props;

  const inner = useRef(null);
  const durRef = useRef(0); // שניות
  const loadedRef = useRef(false);

  // seek נכנס אלינו בשניות (כך עובדים שני הנגנים) ויוצא כשבר.
  // בלי אורך ידוע אין שבר לחשב, ולכן פשוט לא עושים כלום — עדיף לא לקפוץ
  // לתחילת הסרט מאשר לנחש.
  const seek = useCallback(seconds => {
    const d = durRef.current;
    if (!inner.current || !(d > 0)) return;
    const frac = Math.max(0, Math.min(1, (seconds || 0) / d));
    try {
      inner.current.seek(frac);
    } catch (_) {}
  }, []);

  useImperativeHandle(fwdRef, () => ({seek}), [seek]);

  // onLoad מסונתז: הנגנים קוראים בתוכו ל-seek(startTime) כדי להמשיך מאיפה
  // שעצרו, ו-seek מצריך אורך. VLC לא מדווח אורך בפתיחה אלא ב-onPlaying
  // וב-onProgress, ולכן משחררים את onLoad רק כשהאורך באמת ידוע — אחרת
  // ה-seek הראשון היה נופל בשקט וכל "המשך צפייה" היה מתחיל מאפס.
  const fireLoadOnce = useCallback(
    durMs => {
      const d = (durMs || 0) / 1000;
      if (d > 0) durRef.current = d;
      if (loadedRef.current || !(durRef.current > 0)) return;
      loadedRef.current = true;
      // audioTracks/videoTracks קיימים רק כדי שמסך האבחון של הנגן לא
      // יתרסק עליהם. VLC לא מדווח אותם באותו מבנה, ולכן הוא יציג "אין".
      onLoad && onLoad({duration: durRef.current, audioTracks: [], videoTracks: []});
    },
    [onLoad],
  );

  const uri = (source && source.uri) || '';

  return (
    <VLCPlayer
      ref={inner}
      style={[StyleSheet.absoluteFill, style]}
      source={{
        uri,
        initOptions:
          (source && source.initOptions) || DEFAULT_INIT_OPTIONS,
      }}
      paused={!!paused}
      rate={typeof rate === 'number' ? rate : 1}
      resizeMode={resizeMode || 'contain'}
      onPlaying={e => {
        fireLoadOnce(e && e.duration);
      }}
      onProgress={e => {
        const curMs = (e && e.currentTime) || 0;
        const durMs = (e && e.duration) || 0;
        // אם onPlaying לא נשא אורך, זו ההזדמנות השנייה לשחרר את onLoad
        fireLoadOnce(durMs);
        const d = durMs > 0 ? durMs / 1000 : durRef.current;
        onProgress &&
          onProgress({
            currentTime: curMs / 1000,
            seekableDuration: d,
            playableDuration: d,
          });
      }}
      onEnd={() => onEnd && onEnd()}
      onError={e => {
        // מעטפת בצורה שהנגנים מצפים לה (e.error.errorString), כדי שקוד
        // הדיאגנוסטיקה הקיים ימשיך לעבוד בלי שינוי.
        onError &&
          onError({
            error: {
              errorString:
                (e && (e.error || e.message)) ||
                'libVLC לא הצליח לפתוח את המקור',
            },
          });
      }}
      {...rest}
    />
  );
});

export default VlcVideo;
