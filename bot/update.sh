#!/usr/bin/env bash
# סורק מה לא מעודכן אצלך ומעדכן אותו: קוד מהגיט, ספריות פייתון
# חדשות, מודולים שאינם נטענים, כוונונים חדשים ב-.env, מדריך העברית
# שהתיישן, והשירות שרץ על קוד ישן מזה שעל הדיסק.
#
#   bash /opt/zovexsub/bot/update.sh            סריקה + עדכון
#   bash /opt/zovexsub/bot/update.sh --check     סריקה בלבד, לא נוגע
#   bash /opt/zovexsub/bot/update.sh --restart   מפעיל מחדש גם אם עבודה רצה
#
# ברירת המחדל **אינה** מפעילה מחדש כשעבודה רצה, כדי לא להרוג סרט
# באמצע. היא תאמר לך שזה ממתין. ההבדל מ-doctor.sh: הוא בודק את
# ההתקנה (ffmpeg, קודקים, פונטים), וזה בודק מה מעודכן.

set -uo pipefail

ROOT=${ZOVEX_ROOT:-/opt/zovexsub}
REPO="$ROOT/repo"
[[ -d "$REPO/.git" ]] || REPO="$ROOT"
BOT="$REPO/bot"
[[ -d "$BOT" ]] || BOT="$ROOT/bot"
VENV="$ROOT/venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
ENV_FILE="$ROOT/.env"
[[ -f "$ENV_FILE" ]] || ENV_FILE="$(dirname "$BOT")/.env"
SERVICE=${ZOVEX_SERVICE:-zovexsub}

MODE=fix
case "${1:-}" in
  --check)   MODE=check ;;
  --restart) MODE=restart ;;
  "")        ;;
  *) echo "שימוש: update.sh [--check|--restart]"; exit 2 ;;
esac

STALE=0
FAILED=0
NEED_RESTART=0
ok()    { echo "✅ $*"; }
old()   { echo "🔸 $*"; STALE=$((STALE+1)); }
bad()   { echo "❌ $*"; FAILED=$((FAILED+1)); }
head_() { echo; echo "── $* ─────────────────────────"; }

echo "🔄 סריקת עדכונים — $(date '+%Y-%m-%d %H:%M:%S')   [$MODE]"
echo "   קוד: $BOT"

BUSY=0
if pgrep -f "ffmpeg.*zovexsub" >/dev/null 2>&1; then
  BUSY=1
  echo "ℹ️  עבודה רצה כרגע (ffmpeg פעיל)."
fi

# ── 1. קוד מהגיט ──────────────────────────────────────────────
head_ "קוד"
if [[ -d "$REPO/.git" ]]; then
  BRANCH=$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
  DIRTY=$(git -C "$REPO" status --porcelain 2>/dev/null | wc -l)
  git -C "$REPO" fetch --quiet origin "$BRANCH" 2>/dev/null || \
    echo "   (fetch נכשל — אולי אין רשת. ממשיכים עם מה שיש)"
  BEHIND=$(git -C "$REPO" rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null || echo 0)
  AHEAD=$(git -C "$REPO" rev-list --count "origin/$BRANCH..HEAD" 2>/dev/null || echo 0)

  if (( DIRTY > 0 )); then
    # שינוי מקומי שלא נשמר ייעלם ב-pull, ולכן לא נוגעים בו בלי שתדע
    old "$DIRTY קבצים שונו מקומית ולא נשמרו בגיט"
    git -C "$REPO" status --short | head -8 | sed 's/^/     /'
    echo "     ⚠️  לא עושה pull כדי לא לדרוך עליהם."
    echo "     לשמור:  git -C $REPO stash"
    echo "     לזרוק:  git -C $REPO checkout -- ."
  elif (( BEHIND > 0 )); then
    old "$BEHIND קומיטים חדשים מחכים בענף $BRANCH"
    git -C "$REPO" log --oneline "HEAD..origin/$BRANCH" | head -8 | sed 's/^/     /'
    if [[ $MODE != check ]]; then
      if git -C "$REPO" merge --ff-only "origin/$BRANCH" >/dev/null 2>&1; then
        ok "נמשכו $BEHIND קומיטים"
        NEED_RESTART=1
      else
        bad "ה-pull נכשל — ההיסטוריה המקומית התפצלה"
      fi
    fi
  else
    ok "הקוד מעודכן ($BRANCH, $(git -C "$REPO" log -1 --format=%h))"
    (( AHEAD > 0 )) && echo "     ($AHEAD קומיטים מקומיים שלא נדחפו)"
  fi
else
  echo "   אין גיט כאן — מדלג על בדיקת הקוד"
fi

# ── 2. ספריות פייתון ──────────────────────────────────────────
head_ "ספריות פייתון"
if [[ ! -x "$PY" ]]; then
  bad "אין סביבה וירטואלית ב-$VENV — הרץ: bash $BOT/doctor.sh --rebuild"
else
  echo "   $($PY -V 2>&1)"
  REQ="$BOT/requirements.txt"
  if [[ -f "$REQ" ]]; then
    # pip install --dry-run אומר מה **היה** משתנה, בלי לשנות. זו
    # הדרך לשאול "האם חסר משהו" בלי להתקין בסריקה בלבד
    PLAN=$("$PIP" install --dry-run -q -r "$REQ" 2>&1 | \
           grep -i "Would install" || true)
    if [[ -n "$PLAN" ]]; then
      old "ספריות חסרות או מיושנות: ${PLAN#*Would install }"
      if [[ $MODE != check ]]; then
        if "$PIP" install -q -r "$REQ"; then
          ok "הספריות עודכנו"
          NEED_RESTART=1
        else
          bad "התקנת הספריות נכשלה"
        fi
      fi
    else
      ok "כל מה שב-requirements.txt מותקן"
    fi
  else
    echo "   אין requirements.txt — מדלג"
  fi
fi

# ── 3. כל המודולים נטענים ─────────────────────────────────────
# זה השער שתופס מודול חדש שהגיע בגיט ותלוי בספרייה שלא הותקנה.
# בלעדיו התקלה מתגלה רק כשמשתמש שולח סרטון
head_ "מודולים"
if [[ ! -x "$PY" ]]; then
  echo "   אין סביבה וירטואלית — מדלג"
else
  BROKEN=$(cd "$BOT" && "$PY" - <<'PYEOF' 2>&1
import importlib
import pathlib
import sys

bad = []
for path in sorted(pathlib.Path("zovexsub").glob("*.py")):
    if path.name == "__init__.py":
        continue
    try:
        importlib.import_module(f"zovexsub.{path.stem}")
    except Exception as exc:                        # noqa: BLE001
        bad.append(f"{path.stem}: {type(exc).__name__}: {exc}")
print("\n".join(bad))
PYEOF
)
  if [[ -n "$BROKEN" ]]; then
    bad "מודולים שאינם נטענים:"
    echo "$BROKEN" | sed 's/^/     /'
  else
    COUNT=$(ls -1 "$BOT"/zovexsub/*.py | wc -l)
    ok "כל $COUNT המודולים נטענים"
  fi
fi

# ── 4. כוונונים חדשים ב-.env ──────────────────────────────────
# לא תקלה: לכל מפתח יש ברירת מחדל בקוד, והבוט עובד בלעדיו. אבל
# מפתח חדש שאינך יודע עליו הוא תכונה שאינך משתמש בה
head_ "כוונונים"
# מה **חדש מאז ההרצה הקודמת**, ולא כל מפתח שאינו ב-.env שלך. לרוב
# המפתחות יש ברירת מחדל ואינם צריכים להיות אצלך כלל, ולכן רשימה
# מלאה הייתה מדפיסה מאתיים שורות זהות בכל הרצה — רעש ולא סימן
SEEN="$ROOT/.known-keys"
if [[ ! -x "$PY" ]]; then
  echo "   אין סביבה וירטואלית — מדלג"
else
  ALL=$(cd "$BOT" && "$PY" - <<'KEYSCAN' 2>/dev/null
import re
from pathlib import Path

code = Path("zovexsub/config.py").read_text(encoding="utf-8")
keys = set(re.findall(r'_int\(\s*"([A-Z0-9_]+)"', code))
keys |= set(re.findall(r'getenv\(\s*"([A-Z0-9_]+)"', code))
print("\n".join(sorted(keys)))
KEYSCAN
)
  COUNT=$(wc -l <<<"$ALL")
  if [[ ! -f "$SEEN" ]]; then
    echo "ℹ️  $COUNT כוונונים בקוד. רושם אותם כקו הבסיס — מההרצה"
    echo "   הבאה תראה כאן רק את החדשים."
    [[ $MODE != check ]] && printf '%s\n' "$ALL" > "$SEEN"
  else
    FRESH=$(comm -23 <(printf '%s\n' "$ALL" | sort) <(sort "$SEEN"))
    GONE=$(comm -13 <(printf '%s\n' "$ALL" | sort) <(sort "$SEEN"))
    if [[ -n "$FRESH" ]]; then
      old "כוונונים חדשים בקוד מאז ההרצה הקודמת:"
      printf '%s\n' "$FRESH" | sed 's/^/     · /'
      echo "     (לכל אחד יש ברירת מחדל. מי שתרצה לשנות — ל-.env)"
    fi
    if [[ -n "$GONE" ]]; then
      echo "ℹ️  כוונונים שנעלמו מהקוד: $(tr '\n' ' ' <<<"$GONE")"
      # מפתח שנעלם מהקוד ונשאר ב-.env שלך אינו עושה דבר, אבל הוא
      # מטעה: נראה כאילו הוא מכוון משהו
      if [[ -f "$ENV_FILE" ]]; then
        while IFS= read -r key; do
          [[ -z "$key" ]] && continue
          grep -q "^[[:space:]]*$key=" "$ENV_FILE" 2>/dev/null && \
            echo "     ⚠️  $key עוד יושב ב-.env שלך ואינו עושה כלום"
        done <<<"$GONE"
      fi
    fi
    [[ -z "$FRESH" && -z "$GONE" ]] && ok "אין כוונונים חדשים ($COUNT בקוד)"
    [[ $MODE != check ]] && printf '%s\n' "$ALL" > "$SEEN"
  fi
fi
if [[ ! -f "$ENV_FILE" ]]; then
  bad "לא מצאתי .env (חיפשתי ב-$ENV_FILE)"
fi

# ── 4b. הקוד שהשירות באמת מריץ ─────────────────────────────────
# השאלה שמפילה כל פקודת עדכון: הגיט נמשך למקום אחד, והשירות מריץ
# מקום אחר. אז הבדיקות עוברות, ההפעלה מחדש מצליחה, הכל נראה ירוק
# — והבוט ממשיך להריץ את הקוד הישן, בלי שום סימן חיצוני
head_ "הקוד שרץ בפועל"
RUN_DIR=""
if systemctl list-unit-files "$SERVICE.service" >/dev/null 2>&1; then
  UNIT=$(systemctl show -p FragmentPath --value "$SERVICE" 2>/dev/null)
  if [[ -n "${UNIT:-}" && -f "$UNIT" ]]; then
    RUN_DIR=$(grep -oE '^(WorkingDirectory|ExecStart)=[^[:space:]]+' "$UNIT" \
              2>/dev/null | head -1 | cut -d= -f2-)
  fi
fi
if [[ -z "$RUN_DIR" ]]; then
  echo "   לא הצלחתי לקרוא מה-unit איפה השירות רץ — בדוק ידנית:"
  echo "     systemctl cat $SERVICE | grep -E 'WorkingDirectory|ExecStart'"
elif [[ -d "$REPO/.git" ]]; then
  RUN_REAL=$(readlink -f "$RUN_DIR" 2>/dev/null || echo "$RUN_DIR")
  [[ -f "$RUN_REAL" ]] && RUN_REAL=$(dirname "$RUN_REAL")
  BOT_REAL=$(readlink -f "$BOT" 2>/dev/null || echo "$BOT")
  if [[ "$RUN_REAL" == "$BOT_REAL"* || "$BOT_REAL" == "$RUN_REAL"* ]]; then
    ok "השירות מריץ את אותו קוד שעדכנתי"
    echo "     $RUN_REAL"
  else
    bad "השירות מריץ קוד ממקום אחר!"
    echo "     הגיט שעודכן:   $BOT_REAL"
    echo "     מה שרץ בפועל:  $RUN_REAL"
    echo "     כלומר העדכון אינו מגיע לבוט, והכל נראה ירוק."
    echo "     תיקון חד-פעמי (החלפת העותק בקישור לגיט):"
    echo "       systemctl stop $SERVICE"
    echo "       mv $RUN_REAL $RUN_REAL.old"
    echo "       ln -s $BOT_REAL $RUN_REAL"
    echo "       systemctl start $SERVICE"
  fi
fi

# ── 5. הספרייה ומדריך העברית ──────────────────────────────────
head_ "ספריית האולפן"
if [[ ! -x "$PY" ]]; then
  echo "   אין סביבה וירטואלית — מדלג"
else
  (cd "$BOT" && MODE="$MODE" "$PY" - <<'PYEOF' 2>&1 | sed 's/^/   /'
import os
import sys

sys.path.insert(0, ".")
from zovexsub import idiom, learn, memory, studio   # noqa: E402

print(f"ספרייה: {learn.shelf()}")
print(f"זיכרון מובחר: {memory.stats()}")
print(f"בנק סגנון: {len(studio.load_style())} קטעים")
print(f"הפלט שלנו להשוואה: {len(idiom.load_ours())} שורות")

guide = idiom.guide()
# ‫החתימה אומרת אם המדריך שעל הדיסק חושב מהקורפוסים הנוכחיים.
# קבצים נקלטו, או סרטים רצו, והמדריך לא נבנה מחדש — הוא מיושן
fresh = idiom._fingerprint()
cache = idiom._cache_path()
stale = True
if cache.exists():
    try:
        import json
        stale = json.loads(cache.read_text(
            encoding="utf-8")).get("fingerprint") != fresh
    except Exception:                               # noqa: BLE001
        stale = True

if stale and (len(studio.load_style()) or len(idiom.load_ours())):
    print("🔸 מדריך העברית אינו מחושב מהקורפוסים הנוכחיים")
    if os.environ.get("MODE") != "check":
        chars, gender = idiom.build_guide()
        if chars or gender:
            print(f"✅ נבנה מחדש: {chars} תווים + {gender} של פנייה")
        else:
            print("   אין עוד מספיק שורות בשני הצדדים — "
                  f"צריך {__import__('zovexsub.config', fromlist=['x']).IDIOM_MIN_LINES} בכל צד")
elif guide:
    print(f"מדריך העברית: {len(guide)} תווים, מעודכן")
else:
    print("מדריך העברית: ריק (צריך גם קבצי אולפן וגם סרטים שרצו)")
PYEOF
)
fi

# ── 6. בדיקות ─────────────────────────────────────────────────
head_ "בדיקות"
if [[ -x "$PY" && -f "$BOT/tests/run.py" ]]; then
  # הפלט נקרא למשתנה, והקוד נבדק בנפרד. "| tail" מסתיר את קוד
  # היציאה, וזה בדיוק הבאג שגרם לדחיפת בדיקות שבורות בעבר
  OUT=$(cd "$BOT" && "$PY" tests/run.py 2>&1)
  CODE=$?
  echo "$OUT" | tail -2 | sed 's/^/   /'
  if (( CODE == 0 )); then
    ok "הבדיקות עוברות"
  else
    bad "בדיקות נכשלו — אל תפעיל מחדש עד שזה מטופל"
    echo "$OUT" | grep -E "^  ✗" | head -8 | sed 's/^/   /'
  fi
else
  echo "   אין קובץ בדיקות — מדלג"
fi

# ── 7. השירות רץ על הקוד שעל הדיסק? ───────────────────────────
# זה "קבצים שלא עדכנתי": הקוד נמשך מהגיט, אבל התהליך שרץ עדיין
# מחזיק בזיכרון את הגרסה הקודמת. שום דבר לא ייראה שבור — פשוט
# התיקון לא קיים
head_ "שירות"
if systemctl list-unit-files "$SERVICE.service" >/dev/null 2>&1 && \
   systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
  STARTED=$(systemctl show -p ActiveEnterTimestamp --value "$SERVICE" 2>/dev/null)
  # שעת ההתחלה בשניות. ‏find -newermt היה צריך לפרש את פורמט
  # התאריך של systemd, וזה הימור — כשל בפירוש היה מחזיר "אין קוד
  # חדש" בשקט, כלומר בדיוק התשובה הלא נכונה בבדיקה החשובה כאן
  BOOT=$(date -d "$STARTED" +%s 2>/dev/null || echo 0)
  if (( BOOT == 0 )); then
    # נסיגה: זמן ההתחלה של התהליך עצמו
    PID=$(systemctl show -p MainPID --value "$SERVICE" 2>/dev/null)
    [[ -n "${PID:-}" && "$PID" != 0 && -d "/proc/$PID" ]] && \
      BOOT=$(stat -c %Y "/proc/$PID" 2>/dev/null || echo 0)
  fi
  if (( BOOT == 0 )); then
    echo "   לא הצלחתי לקבוע מאימתי השירות רץ — בדוק ידנית"
  else
    NEWEST=""
    while IFS= read -r file; do
      (( $(stat -c %Y "$file" 2>/dev/null || echo 0) > BOOT )) && \
        NEWEST+="$file"$'\n'
    done < <(find "$BOT" -name '*.py' 2>/dev/null)
    if [[ -n "$NEWEST" ]]; then
      NEED_RESTART=1
      old "השירות רץ מ-$STARTED, ויש קוד חדש ממנו:"
      printf '%s' "$NEWEST" | head -6 | sed "s|$BOT/|     · |"
    else
      ok "השירות רץ על הקוד שעל הדיסק (מאז $STARTED)"
    fi
  fi

  if (( NEED_RESTART )); then
    if (( FAILED > 0 )); then
      echo "   ⛔ לא מפעיל מחדש: יש כשלים למעלה."
    elif [[ $MODE == check ]]; then
      echo "   (סריקה בלבד — להפעלה: systemctl restart $SERVICE)"
    elif (( BUSY )) && [[ $MODE != restart ]]; then
      echo "   ⏸️  עבודה רצה כרגע, ולכן לא מפעיל מחדש — זה היה הורג"
      echo "      אותה באמצע. כשתסתיים:  systemctl restart $SERVICE"
      echo "      או עכשיו בכל מקרה:      bash $0 --restart"
    else
      echo "   מפעיל מחדש..."
      if systemctl restart "$SERVICE"; then
        sleep 2
        if systemctl is-active --quiet "$SERVICE"; then
          ok "השירות הופעל מחדש ורץ"
        else
          bad "השירות לא עלה. ‏journalctl -u $SERVICE -n 40"
        fi
      else
        bad "ההפעלה מחדש נכשלה"
      fi
    fi
  fi
elif systemctl list-unit-files "$SERVICE.service" >/dev/null 2>&1; then
  bad "השירות $SERVICE מוגדר אבל אינו רץ. ‏systemctl start $SERVICE"
else
  echo "   אין שירות systemd בשם $SERVICE — מדלג"
fi

# ── סיכום ─────────────────────────────────────────────────────
echo
if (( FAILED > 0 )); then
  echo "❌ $FAILED כשלים. תקן אותם לפני שתפעיל מחדש."
  exit 1
fi
if (( STALE > 0 )); then
  if [[ $MODE == check ]]; then
    echo "🔸 $STALE דברים לא מעודכנים. להרצה אמיתית: bash $0"
  else
    echo "✅ הכל עודכן ($STALE דברים טופלו)."
  fi
  exit 0
fi
echo "✅ הכל מעודכן. אין מה לעשות."
