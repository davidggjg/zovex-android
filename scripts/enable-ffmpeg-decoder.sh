#!/usr/bin/env bash
# מדליק את מפענח ה-FFmpeg של Media3 בתוך react-native-video.
#
# ## למה בכלל
#
# תוכן מקודד ב-Dolby Digital Plus (ec-3) — ונסדיי, למשל — לא מתפענח לא
# ב-WebView ולא ב-ExoPlayer מהקופסה. אנדרואיד לא מחייב את היצרנים לכלול
# מפענח Dolby, וברוב הטלפונים הוא פשוט לא קיים. ExoPlayer מדלג על הרצועה
# בשקט, בלי שום אירוע error, ומקבלים וידאו בלי קול.
#
# ל-Media3 יש הרחבה שמביאה את המפענחים של FFmpeg — אותה משפחת מפענחים
# ש-VLC משתמש בה, וזו הסיבה ש-VLC ניגן את ונסדיי כל הזמן. ההרחבה **אינה**
# מגיעה בנויה מגוגל: צריך לקמפל אותה עם NDK. אבל Jellyfin מפרסמים אותה
# בנויה ל-Maven Central, וזה מוריד את כל העבודה הזאת לשורת Gradle אחת.
#
# אומת על ה-AAR עצמו (org.jellyfin.media3:media3-ffmpeg-decoder:1.3.1+2):
#
#   ff_eac3_decoder  ff_ac3_decoder  ff_dca_decoder  ff_truehd_decoder
#   ff_mlp_decoder   ff_aac_decoder  + alac/flac/mp3/pcm
#
#   arm64-v8a 1.4MB · armeabi-v7a 1.3MB · x86 1.4MB · x86_64 1.5MB
#
# הגרסה 1.3.1 אינה מקרית — זו בדיוק גרסת media3 ש-react-native-video 6.4.5
# משתמש בה (RNVideo_media3Version=1.3.1). התאמה בין השתיים היא חובה.
#
# ## למה צריך סקריפט ולא רק תלות
#
# react-native-video מקבע EXTENSION_RENDERER_MODE_OFF בקוד, בלי שום דגל
# בנייה לשנות את זה. כלומר גם אם ההרחבה נמצאת ב-classpath, ExoPlayer לא
# ייגע בה. השורה הזאת חייבת להשתנות ל-PREFER.
#
# PREFER ולא ON: ההרחבה מקבלת עדיפות על מפענח החומרה **רק** לפורמטים
# שהיא תומכת בהם. כל השאר — H.264, AAC רגיל, כל 11,900 הפריטים האחרים —
# ממשיכים לרוץ על שבב הפענוח של המכשיר, בלי שינוי ובלי עלות סוללה.
#
# ## הסקריפט נכשל בקול
#
# אם השורה לא נמצאה — שדרוג של react-native-video, למשל — הסקריפט עוצר
# את הבנייה. חלופה שבה הבנייה מצליחה והקול פשוט נעלם שוב היא בדיוק סוג
# התקלה שלוקח שבועות לגלות.
set -euo pipefail

F="node_modules/react-native-video/android/src/main/java/com/brentvatne/exoplayer/ReactExoplayerView.java"
OLD="EXTENSION_RENDERER_MODE_OFF"
NEW="EXTENSION_RENDERER_MODE_PREFER"

[[ -f "$F" ]] || { echo "❌ לא נמצא $F"; exit 1; }

if grep -q "$NEW" "$F"; then
  echo "✓ כבר מודלק ($NEW)"
  exit 0
fi

n=$(grep -c "setExtensionRendererMode(DefaultRenderersFactory.$OLD)" "$F" || true)
if [[ "$n" != "1" ]]; then
  echo "❌ נמצאו $n התאמות ל-$OLD, ציפינו ל-1."
  echo "   react-native-video כנראה השתנה. בלי התיקון הזה אין קול ב-ec-3,"
  echo "   ואני מעדיף שהבנייה תיפול מאשר שזה יחזור בשקט."
  exit 1
fi

sed -i "s/setExtensionRendererMode(DefaultRenderersFactory.$OLD)/setExtensionRendererMode(DefaultRenderersFactory.$NEW)/" "$F"
grep -q "$NEW" "$F" || { echo "❌ ההחלפה לא נתפסה"; exit 1; }
echo "✓ $OLD → $NEW"
