#!/usr/bin/env bash
# נותן ל-ExoPlayer מגבלות זמן על בקשות HTTP. בלי זה ערוץ חי שלא עונה תוקע
# את הנגן לנצח במקום להיכשל.
#
# ## התסמין
#
# ערוץ חי: ספינר אינסופי. onLoad לא נורה אף פעם, onError לא נורה אף פעם,
# ולכן גם שרשרת הנפילה-אחורה (VLC → ExoPlayer → WebView) לא נדרכת — אין
# שגיאה שתדרוך אותה. הנגן פשוט תקוע.
#
# ## הסיבה
#
# react-native-video בונה את שכבת ה-HTTP שלו כך (אומת ב-6.4.5,
# android/src/main/java/com/brentvatne/exoplayer/DataSourceUtil.kt):
#
#     val client = OkHttpClientProvider.getOkHttpClient()
#
# וה-OkHttpClient של React Native מוגדר שם עם
#
#     .connectTimeout(0, MILLISECONDS)
#     .readTimeout(0, MILLISECONDS)
#     .writeTimeout(0, MILLISECONDS)
#
# כלומר **אינסוף**. זה הגיוני ל-fetch של JS (שם ה-JS מנהל את הזמן בעצמו),
# אבל לנגן וידאו זה אסון: אם השרת פותח חיבור ואז לא שולח בייטים — מה שקורה
# לספקי IPTV שמעירים ערוץ, או שחונקים לקוח שאינו נגן מוכר — ExoPlayer ממתין
# לנצח על אותה בקשה. אין timeout, ולכן אין שגיאה, ולכן אין ניסיון חוזר ואין
# נפילה אחורה.
#
# ## התיקון
#
# גוזרים לקוח משלנו מאותו לקוח (newBuilder משתף את מאגר החיבורים ואת
# ה-cookieJar, ולכן שאר הקוד בקובץ ממשיך לעבוד) ונותנים לו מגבלות זמן
# אמיתיות. מרגע זה בקשה תקועה נכשלת, ExoPlayer מנסה שוב לפי
# minLoadRetryCount, ואם גם זה נכשל — onError נורה והשרשרת שלנו עובדת.
#
# readTimeout הוא פער בין בייטים ולא תקרה לבקשה כולה, ולכן 20 שניות אינן
# מגבילות סגמנט ארוך שזורם כרגיל; הן חותכות רק חיבור שבאמת שותק.
#
# אם הקוד של החבילה השתנה — מזהיר ולא מפיל את הבנייה, כמו שאר הטלאים.
set -euo pipefail

F="node_modules/react-native-video/android/src/main/java/com/brentvatne/exoplayer/DataSourceUtil.kt"
[[ -f "$F" ]] || { echo "::warning::לא נמצא $F — טלאי ה-timeouts לא הוחל"; exit 0; }

if grep -q "ZOVEX_HTTP_TIMEOUTS" "$F"; then
  echo "✓ כבר מתוקן (http timeouts)"
  exit 0
fi

python3 - "$F" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p, encoding='utf-8').read()
pat = re.compile(r'val client = OkHttpClientProvider\.getOkHttpClient\(\)')
n = len(pat.findall(s))
if n != 1:
    print("::warning::נמצאו %d התאמות ל-getOkHttpClient(), ציפינו ל-1 - התיקון לא הוחל" % n)
    sys.exit(0)
repl = (
    '// ZOVEX_HTTP_TIMEOUTS\n'
    '        val client = OkHttpClientProvider.getOkHttpClient()\n'
    '            .newBuilder()\n'
    '            .connectTimeout(15, java.util.concurrent.TimeUnit.SECONDS)\n'
    '            .readTimeout(20, java.util.concurrent.TimeUnit.SECONDS)\n'
    '            .writeTimeout(20, java.util.concurrent.TimeUnit.SECONDS)\n'
    '            .retryOnConnectionFailure(true)\n'
    '            .build()'
)
s = pat.sub(repl, s, count=1)
open(p, 'w', encoding='utf-8').write(s)
PY

grep -q "ZOVEX_HTTP_TIMEOUTS" "$F" || { echo "::warning::ההחלפה לא נתפסה"; exit 0; }
echo "✓ HTTP: connect=15s read=20s write=20s (במקום אינסוף)"
