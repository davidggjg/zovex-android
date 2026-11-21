#!/usr/bin/env bash
# בודק ומתקן את כל ההתקנה של zovexsub: חבילות מערכת, פונטים,
# סביבת פייתון, ספריות, ffmpeg וקודקים. לא מפעיל מחדש את השירות
# ולא נוגע ב-.env — אפשר להריץ גם כשעבודה רצה.
#
#   bash /opt/zovexsub/bot/doctor.sh            בדיקה + תיקון
#   bash /opt/zovexsub/bot/doctor.sh --check    בדיקה בלבד
#   bash /opt/zovexsub/bot/doctor.sh --rebuild  בונה את ה-venv מאפס

set -uo pipefail

ROOT=${ZOVEX_ROOT:-/opt/zovexsub}
BOT="$ROOT/bot"
VENV="$ROOT/venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

MODE=fix
case "${1:-}" in
  --check)   MODE=check ;;
  --rebuild) MODE=rebuild ;;
  "")        ;;
  *) echo "שימוש: doctor.sh [--check|--rebuild]"; exit 2 ;;
esac

PROBLEMS=0
ok()   { echo "✅ $*"; }
warn() { echo "⚠️  $*"; PROBLEMS=$((PROBLEMS+1)); }
bad()  { echo "❌ $*"; PROBLEMS=$((PROBLEMS+1)); }
head_() { echo; echo "── $* ─────────────────────────"; }

echo "🩺 בדיקת התקנה — $(date '+%H:%M:%S')   [$MODE]"

if systemctl is-active --quiet zovexsub 2>/dev/null; then
  echo "ℹ️  השירות רץ. הסקריפט לא יפעיל אותו מחדש ולא יעצור עבודה."
fi

# ── 1. חבילות מערכת ───────────────────────────────────────────
head_ "חבילות מערכת"
NEED=(ffmpeg ffprobe git curl fc-list)
MISSING=()
for tool in "${NEED[@]}"; do
  command -v "$tool" >/dev/null 2>&1 || MISSING+=("$tool")
done
if ((${#MISSING[@]})); then
  warn "חסר: ${MISSING[*]}"
  if [[ $MODE != check ]] && command -v apt-get >/dev/null 2>&1; then
    echo "   מתקין..."
    apt-get update -qq
    apt-get install -y -qq ffmpeg python3-venv python3-pip git curl fontconfig \
      && ok "חבילות המערכת הותקנו" || bad "ההתקנה נכשלה — הרץ עם sudo"
  fi
else
  ok "ffmpeg, ffprobe, git, curl — קיימים"
fi

# ── 2. קודק x265 (הצריבה שלנו) ────────────────────────────────
head_ "קודקים"
# הפלט נקרא למשתנה ולא נבדק בצינור. עם pipefail, ‏grep -q יוצא
# ברגע שהוא מוצא, שולח SIGPIPE ל-ffmpeg, ו-ffmpeg מת עם קוד שגיאה —
# ואז הצינור כולו נחשב כישלון. נמדד: הבדיקה דיווחה "libx265 חסר"
# בכל הרצה, בזמן ששנים־עשר מקודדי x265 רצו על אותה מכונה
ENCODERS=$(ffmpeg -hide_banner -encoders 2>/dev/null || true)
FILTERS=$(ffmpeg -hide_banner -filters 2>/dev/null || true)

case "$ENCODERS" in
  *libx265*) ok "libx265 — זמין (זו שיטת הצריבה שלנו: x265 + CRF)" ;;
  *) bad "libx265 חסר! הצריבה תיפול. צריך ffmpeg עם --enable-libx265" ;;
esac
case "$FILTERS" in
  *" subtitles "*) ok "פילטר subtitles — זמין" ;;
  *) bad "פילטר subtitles חסר — אי אפשר לצרוב כתוביות" ;;
esac

# ── 3. פונט עברי ──────────────────────────────────────────────
head_ "פונט עברי"
HEBREW_FONTS=$(fc-list :lang=he 2>/dev/null | wc -l || echo 0)
if command -v fc-list >/dev/null 2>&1 && [ "${HEBREW_FONTS:-0}" -gt 0 ]; then
  ok "יש פונט עברי ($HEBREW_FONTS גרסאות)"
else
  warn "אין פונט עברי — הכתוביות הצרובות ייצאו ריבועים"
  if [[ $MODE != check ]] && command -v apt-get >/dev/null 2>&1; then
    apt-get install -y -qq fonts-noto-core fonts-dejavu >/dev/null 2>&1
    apt-get install -y -qq fonts-noto-hebrew >/dev/null 2>&1 || true
    fc-cache -f >/dev/null 2>&1
    HEBREW_FONTS=$(fc-list :lang=he 2>/dev/null | wc -l || echo 0)
    [ "${HEBREW_FONTS:-0}" -gt 0 ] \
      && ok "פונט עברי הותקן" || bad "עדיין אין פונט עברי"
  fi
fi

# ── 4. סביבת פייתון ───────────────────────────────────────────
head_ "סביבת פייתון"
if [[ $MODE == rebuild ]]; then
  BEST=$(for v in 3.13 3.12 3.11 3; do
           command -v "python$v" >/dev/null 2>&1 && { echo "python$v"; break; }
         done)
  echo "   בונה venv מאפס עם $BEST..."
  rm -rf "$VENV"
  "$BEST" -m venv "$VENV" && ok "venv נבנה מחדש" || bad "בניית venv נכשלה"
fi

if [[ ! -x $PY ]]; then
  bad "אין venv ב-$VENV — הרץ עם --rebuild"
else
  VER=$($PY -c 'import sys; print("%d.%d"%sys.version_info[:2])')
  MAJ=${VER%%.*}; MIN=${VER##*.}
  if (( MAJ > 3 || MIN >= 11 )); then
    ok "פייתון $VER"
  else
    warn "פייתון $VER — yt-dlp כבר לא תומך בזה רשמית."
    NEWER=$(for v in 3.13 3.12 3.11; do
              command -v "python$v" >/dev/null 2>&1 && { echo "python$v"; break; }
            done)
    if [[ -n $NEWER ]]; then
      echo "   יש $NEWER במערכת. לשדרוג:  bash $BOT/doctor.sh --rebuild"
    else
      echo "   אין פייתון חדש יותר במערכת. להתקנה: apt install python3.12-venv"
    fi
  fi
fi

# ── 5. ספריות ─────────────────────────────────────────────────
head_ "ספריות פייתון"
if [[ -x $PIP && $MODE != check ]]; then
  echo "   מעדכן לפי requirements.txt..."
  $PIP install -q --upgrade pip >/dev/null 2>&1
  if $PIP install -q --upgrade -r "$BOT/requirements.txt"; then
    ok "כל הספריות עודכנו"
  else
    bad "pip נכשל — ראה את השגיאה למעלה"
  fi
  # yt-dlp מתיישן מהר ושובר הורדות מיוטיוב/דרייב
  $PIP install -q --upgrade yt-dlp >/dev/null 2>&1 && ok "yt-dlp עודכן לאחרון"
fi

if [[ -x $PY ]]; then
  $PY - <<'PYCHECK'
import importlib, sys
critical = {
    "telethon":    "העברות טלגרם",
    "cryptg":      "הצפנה מהירה — בלעדיה ההורדה איטית פי עשרות",
    "httpx":       "קריאות API",
    "yt_dlp":      "הורדה מקישור",
    "dotenv":      "קריאת .env",
    "onnxruntime": "זיהוי דיבור VAD",
    "numpy":       "עיבוד אודיו",
    "google.genai":"ג'ימיני",
    "pyflakes":    "בדיקה סטטית",
}
bad = 0
for mod, why in critical.items():
    try:
        m = importlib.import_module(mod)
        v = getattr(m, "__version__", "")
        if mod == "yt_dlp":
            v = m.version.__version__
        print(f"  ✅ {mod:<14} {v:<12} {why}")
    except Exception as exc:
        print(f"  ❌ {mod:<14} {'':<12} חסר! ({why}) — {exc}")
        bad += 1
sys.exit(1 if bad else 0)
PYCHECK
  [[ $? -eq 0 ]] || bad "חסרות ספריות קריטיות"
fi

# ── 6. הגדרות ומפתחות ─────────────────────────────────────────
head_ "הגדרות"
if [[ ! -f $BOT/.env ]]; then
  bad "אין קובץ .env ב-$BOT"
else
  perm=$(stat -c '%a' "$BOT/.env")
  [[ $perm == 600 ]] && ok ".env מוגן (600)" \
                     || warn ".env בהרשאות $perm — כדאי chmod 600"
  [[ -x $PY ]] && (cd "$BOT" && $PY - <<'PYCONF'
from zovexsub import config
g, m = len(config.GROQ_API_KEYS), len(config.GEMINI_API_KEYS)
print(f"  {'✅' if g else '❌'} מפתחות Groq:   {g}")
print(f"  {'✅' if m else '❌'} מפתחות Gemini: {m}")
print(f"  ℹ️  ליבות לצריבה: {config.BURN_THREADS}")
issues = config.validate()
print(f"  {'⚠️ ' if issues else '✅'} {issues or 'אין בעיות בהגדרות'}")
PYCONF
  )
fi

# ── 7. מקום בדיסק ─────────────────────────────────────────────
head_ "דיסק"
AVAIL=$(df -BG --output=avail "$ROOT" 2>/dev/null | tail -1 | tr -dc '0-9')
if [[ -n $AVAIL ]]; then
  (( AVAIL >= 20 )) && ok "פנוי ${AVAIL}G" \
                    || warn "פנוי רק ${AVAIL}G — סרט אחד יכול לדרוש יותר"
fi

# ── 8. הבדיקות שלנו ───────────────────────────────────────────
head_ "בדיקות הקוד"
if [[ -x $PY && -f $BOT/tests/run.py ]]; then
  (cd "$BOT" && $PY tests/run.py) && ok "כל הבדיקות עברו" \
                                  || bad "בדיקות נפלו — אל תפרוס"
fi

# ── סיכום ─────────────────────────────────────────────────────
echo
if (( PROBLEMS == 0 )); then
  echo "🟢 הכל תקין. אין מה לתקן."
else
  echo "🟡 $PROBLEMS דברים לטיפול — ראה ⚠️/❌ למעלה."
fi
exit 0
