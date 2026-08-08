import React, {useEffect} from 'react';
import {StyleSheet} from 'react-native';
import {CastButton, useRemoteMediaClient} from 'react-native-google-cast';

// ── שכבת Google Cast מבודדת ────────────────────────────────────────────────────
// כל השימוש ב-Cast (ה-hook והכפתור) מרוכז כאן, כדי שהרכיב הזה יעלה *רק* אחרי
// שווידאנו ש-Google Play Services זמין. Cast נשען על CastContext.getSharedInstance
// שדורש GMS + Cast SDK — ועל מכשירים בלי GMS (טלפוני Qin, חלק מהטלוויזיות) עצם
// הגישה אליו זורקת ומקריסה את האפליקציה. הרכיב מותנה-הרכבה מונע את זה לגמרי.
export default function CastLayer({
  castUrl,
  contentType,
  isLive,
  title,
  images,
  startTime,
  onCasting,
}) {
  const client = useRemoteMediaClient();
  useEffect(() => {
    if (!client) return;
    client
      .loadMedia({
        mediaInfo: {
          contentUrl: castUrl,
          contentType,
          metadata: {type: isLive ? 'generic' : 'movie', title, images},
        },
        startTime: Math.floor(isLive ? 0 : startTime || 0),
      })
      .catch(() => {});
    onCasting && onCasting();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, castUrl, contentType, isLive, startTime]);

  return <CastButton style={styles.btn} />;
}

const styles = StyleSheet.create({
  btn: {position: 'absolute', top: 10, right: 12, width: 40, height: 40, tintColor: '#fff', zIndex: 20},
});
