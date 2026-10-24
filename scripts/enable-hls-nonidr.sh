#!/usr/bin/env bash
# מלמד את ExoPlayer (בתוך react-native-video) לנגן שידורי IPTV חיים שה-
# keyframes שלהם אינם IDR.
#
# ## התסמין
#
# ערוץ חי נטען לנצח: ספינר, "LIVE", שום שגיאה — וב-VLC אותה כתובת עולה תוך
# שנייה. ה-relay עונה מהר והרשימה תקינה.
#
# ## הסיבה
#
# רבים משידורי ה-IPTV (קודנים של פאנלים) מתחילים כל קטע ב-I-slice רגיל
# ולא ב-IDR. ברירת המחדל של קורא ה-TS ב-ExoPlayer מסמנת כ-keyframe רק IDR,
# ולכן הוא זורק וידאו, ממלא את הבאפר באודיו ונשאר ב-BUFFERING עד timeout.
# VLC לא מקפיד על זה. התיקון הידוע (גם בפרויקטים אחרים, ראו issue #8587 של
# ExoPlayer) הוא לבנות את מקור ה-HLS עם extractor שמקבל את הדגלים:
#   FLAG_ALLOW_NON_IDR_KEYFRAMES | FLAG_DETECT_ACCESS_UNITS
#
# react-native-video בונה את HlsMediaSource בלי אפשרות להעביר extractor,
# ולכן מתקנים בקוד שלו, כמו בסקריפט ה-FFmpeg. אם הקוד השתנה הסקריפט
# מזהיר (::warning::) אבל לא מפיל את הבנייה: זה תיקון לשיפור, לא תנאי להפעלה.
set -euo pipefail

F="node_modules/react-native-video/android/src/main/java/com/brentvatne/exoplayer/ReactExoplayerView.java"
[[ -f "$F" ]] || { echo "❌ לא נמצא $F"; exit 1; }

if grep -q "FLAG_ALLOW_NON_IDR_KEYFRAMES" "$F"; then
  echo "✓ כבר מתוקן (non-IDR)"
  exit 0
fi

python3 - "$F" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p, encoding='utf-8').read()
pat = re.compile(r'new\s+HlsMediaSource\.Factory\(\s*mediaDataSourceFactory\s*\)')
found = pat.findall(s)
if len(found) != 1:
    print("::warning::נמצאו %d התאמות ל-HlsMediaSource.Factory, ציפינו ל-1 - התיקון לא הוחל" % len(found))
    sys.exit(0)
repl = ('new HlsMediaSource.Factory(mediaDataSourceFactory)'
        '.setExtractorFactory(new androidx.media3.exoplayer.hls.DefaultHlsExtractorFactory('
        'androidx.media3.extractor.ts.DefaultTsPayloadReaderFactory.FLAG_ALLOW_NON_IDR_KEYFRAMES'
        ' | androidx.media3.extractor.ts.DefaultTsPayloadReaderFactory.FLAG_DETECT_ACCESS_UNITS,'
        ' true))')
s = pat.sub(repl, s, count=1)
open(p, 'w', encoding='utf-8').write(s)
PY
grep -q "FLAG_ALLOW_NON_IDR_KEYFRAMES" "$F" || { echo "::warning::ההחלפה לא נתפסה"; exit 0; }
echo "✓ HLS: FLAG_ALLOW_NON_IDR_KEYFRAMES | FLAG_DETECT_ACCESS_UNITS"
