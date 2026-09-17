#!/usr/bin/env bash
# מתקן קריסה בזמן ריצה ב-react-native-vlc-media-player 1.0.98.
#
# ## התסמין
#
# האפליקציה מתקמפלת ונפתחת, אבל לחיצה על פליי מקריסה אותה מיד. דטרמיניסטי,
# על כל קובץ.
#
# ## השורש
#
# ReactVlcPlayerViewManager.setSrc קורא:
#
#     boolean autoplay = src.getBoolean("autoplay") ? ... : true;
#
# בלי hasKey. אבל הצד ה-JS של החבילה (VLCPlayer.js) בונה את מפת src עם
# uri, isNetwork, isAsset, type, mainVer, patchVer **בלבד** — הוא שם את
# autoplay על ה-prop ‏source, שאין לו בכלל @ReactProp נייטיבי. כלומר
# המפתח "autoplay" לעולם אינו קיים ב-src, ו-ReadableMap.getBoolean על
# מפתח חסר זורק NoSuchKeyException. זו חריגה קטלנית, והיא נזרקת בדיוק
# כשה-prop ‏src נקבע — כלומר ברגע שמתחילים לנגן.
#
# ReactVlcPlayerView.java, המימוש האמיתי, עושה את אותה שורה **נכון**
# (שורה 357: hasKey("autoplay") ? ... : true). ב-ViewManager יש עותק שבור
# שלה, ושלושת המשתנים שהוא מחשב — autoplay, extension, isNetStr — אינם
# בשימוש בכלל: הפונקציה רק בודקת שה-uri לא ריק וקוראת ל-videoView.setSrc.
# כלומר זה קוד מת שמקריס, ולכן התיקון בטוח לחלוטין: הוא לא משנה שום
# התנהגות, רק מונע את החריגה.
#
# isNetStr מוגן כאן גם הוא. המפתח שלו כן קיים, ולכן הוא לא קורס היום, אבל
# הוא מסתמך על אותה הנחה שגויה.
#
# ## למה סקריפט ולא fork
#
# זו אותה גישה של scripts/enable-ffmpeg-decoder.sh: npm install דורס את
# node_modules, ולכן התיקון חייב לרוץ אחריו ולפני הבנייה. הסקריפט נופל
# בקול אם השורה שהוא מחפש כבר לא שם — אם גרסה חדשה של החבילה תתקן את זה
# בעצמה, אני מעדיף שהבנייה תיפול ואבדוק, מאשר שפאץ' ישקוט ויפספס.
set -euo pipefail

F="node_modules/react-native-vlc-media-player/android/src/main/java/com/yuanzhou/vlc/vlcplayer/ReactVlcPlayerViewManager.java"

[[ -f "$F" ]] || { echo "❌ לא נמצא $F"; exit 1; }

if grep -q 'hasKey("autoplay")' "$F"; then
  echo "✓ כבר מתוקן (autoplay מוגן ב-hasKey)"
  exit 0
fi

OLD_AUTOPLAY='boolean autoplay = src.getBoolean("autoplay") ? src.getBoolean("autoplay") : true;'
NEW_AUTOPLAY='boolean autoplay = !src.hasKey("autoplay") || src.getBoolean("autoplay");'

n=$(grep -cF "$OLD_AUTOPLAY" "$F" || true)
if [[ "$n" != "1" ]]; then
  echo "❌ נמצאו $n התאמות לשורת autoplay, ציפינו ל-1."
  echo "   react-native-vlc-media-player כנראה השתנתה. בלי התיקון הזה"
  echo "   האפליקציה קורסת בלחיצה על פליי, ולכן מוטב שהבנייה תיפול כאן."
  exit 1
fi

python3 - "$F" "$OLD_AUTOPLAY" "$NEW_AUTOPLAY" <<'PY'
import sys
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(path, encoding='utf-8').read()
assert s.count(old) == 1
s = s.replace(old, new, 1)

# אותה הנחה שגויה, מפתח שכן קיים ולכן לא קורס היום. מוגן בדרך.
old_net = 'boolean isNetStr = src.getBoolean(PROP_SRC_IS_NETWORK) ? src.getBoolean(PROP_SRC_IS_NETWORK) : false;'
new_net = 'boolean isNetStr = src.hasKey(PROP_SRC_IS_NETWORK) && src.getBoolean(PROP_SRC_IS_NETWORK);'
if s.count(old_net) == 1:
    s = s.replace(old_net, new_net, 1)
    print('  + isNetwork מוגן גם הוא')

open(path, 'w', encoding='utf-8').write(s)
PY

grep -q 'hasKey("autoplay")' "$F" || { echo "❌ ההחלפה לא נתפסה"; exit 1; }
echo "✓ autoplay מוגן ב-hasKey — לחיצה על פליי לא תקריס יותר"
