"""הגדרות שנטענות מ-.env. מפתחות אמיתיים לא נכנסים לקוד ולא לגיט."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _keys(name: str) -> list[str]:
    raw = os.getenv(name, "") or ""
    return [k.strip() for k in raw.replace("\n", ",").split(",") if k.strip()]


TG_API_ID = _int("TG_API_ID", 0)
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION = os.getenv("TG_SESSION", "zovexsub")

TRIGGER = os.getenv("TRIGGER", ".srt")

# רשימת המורשים נשמרת כאן ומנוהלת מתוך טלגרם (.allow / .deny / .users)
ALLOWLIST_FILE = os.getenv(
    "ALLOWLIST_FILE", str(Path(__file__).resolve().parent.parent / "allowlist.json")
)

GROQ_API_KEYS = _keys("GROQ_API_KEYS")
GEMINI_API_KEYS = _keys("GEMINI_API_KEYS")

GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3")
# מודל גיבוי לתמלול. turbo זול ומהיר יותר, מדויק מעט פחות, ולרוב פחות
# עמוס — שווה לנסות אותו כששרתי המודל הראשי מחזירים 502
GROQ_STT_FALLBACK = os.getenv("GROQ_STT_FALLBACK", "whisper-large-v3-turbo")
# כמה סבלנות לתת לתקלה זמנית אצל הספק לפני שמנסים דרך אחרת
STT_ATTEMPTS = _int("STT_ATTEMPTS", 10)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-pro-latest")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-flash-latest")
GEMINI_LAST_RESORT_MODEL = os.getenv("GEMINI_LAST_RESORT_MODEL", "gemini-flash-lite-latest")
# מעבר החקר לא קריטי — אחריו ממשיכים בלעדיו במקום להחזיק את התור
RESEARCH_TIMEOUT = _int("RESEARCH_TIMEOUT", 180)

MAX_INPUT_MINUTES = _int("MAX_INPUT_MINUTES", 180)
BURN_MAX_MINUTES = _int("BURN_MAX_MINUTES", 10)
# פרופילי צריבה. CRF הוא קידוד לפי איכות ולא לפי bitrate — הוא מוציא
# ביטים בסצנות מורכבות וחוסך בפשוטות, כלומר מקטין בדיוק היכן שהעין
# לא שמה לב.
#
# נמדד על מקור גרעיני 1080p לפלט 720p, 60 שניות, ארבע ליבות:
#   H.264 veryfast crf28   24s   7564KB
#   H.265 veryfast crf30   32s   4164KB   (45% פחות)
#   H.265 medium   crf30   63s   3796KB   (עוד 9% פחות, פי שניים זמן)
#   H.265 10bit            38s   4216KB   (לא הקטין כאן)
#   H.265 tune grain       74s   9144KB   (משמר גרעיניות - מגדיל פי 2.4)
#   AV1 svt preset 8       50s  10580KB   (איטי וגדול יותר)
PROFILES = {
    # H.264 — נתמך בכל מקום, הקובץ הגדול ביותר
    "fast": {"codec": "libx264", "preset": "veryfast", "crf": 28,
             "pix_fmt": "yuv420p", "tune": ""},
    # H.265 — כמחצית הגודל, נתמך בטלגרם וברוב המכשירים המודרניים
    "balanced": {"codec": "libx265", "preset": "veryfast", "crf": 30,
                 "pix_fmt": "yuv420p", "tune": ""},
    # H.265 עם preset איטי יותר — אותה איכות, קובץ קטן יותר, פי שניים מעבד
    "small": {"codec": "libx265", "preset": "medium", "crf": 30,
              "pix_fmt": "yuv420p", "tune": ""},
}

BURN_PROFILE = (os.getenv("BURN_PROFILE") or "balanced").strip().lower()
_profile = PROFILES.get(BURN_PROFILE, PROFILES["balanced"])

# כל ערך בפרופיל ניתן לדריסה נקודתית ב-.env
BURN_CODEC = os.getenv("BURN_CODEC") or _profile["codec"]
BURN_PRESET = os.getenv("BURN_PRESET") or _profile["preset"]
BURN_CRF = _int("BURN_CRF", _profile["crf"])
BURN_PIX_FMT = os.getenv("BURN_PIX_FMT") or _profile["pix_fmt"]
BURN_TUNE = os.getenv("BURN_TUNE", _profile["tune"])

# תקרת bitrate קשיחה מעוותת את האיכות: סצנה מורכבת נחנקת בדיוק כשהיא
# צריכה ביטים. CRF לבדו מחלק את הביטים נכון, ולכן התקרה כבויה כברירת
# מחדל. ערך גדול מאפס מפעיל אותה, למקרה שחייבים להיכנס בגודל מסוים.
UPLOAD_LIMIT_MB = _int("UPLOAD_LIMIT_MB", 0)
# תקרת רזולוציה. המקור אף פעם לא מוגדל — רק 4K וגבוה מזה יורד ל-1080p,
# כדי שהצריבה לא תימשך נצח. 0 מבטל כל שינוי רזולוציה.
BURN_MAX_HEIGHT = _int("BURN_MAX_HEIGHT", 1080)
FFMPEG_THREADS = _int("FFMPEG_THREADS", 1)
# לצריבה כדאי יותר מ-thread אחד: הצוואר הוא פענוח המקור, ושתי ליבות
# מכפילות את המהירות פי 2.4 בלי לשנות את גודל הפלט. חלון ההפרעה מתקצר,
# וה-nice ממילא מוותר על המעבד לכל תהליך אחר
BURN_THREADS = _int("BURN_THREADS", 2)
# תקרה קשיחה לצריבה. תוכן גרעיני מקודד לאט מזמן אמת, ובלי תקרה קובץ
# חריג יכול לרוץ שעה על שרת עמוס
BURN_TIMEOUT = _int("BURN_TIMEOUT", 1800)
# בדיקת מקום בדיסק לפני הורדה וצריבה: פי כמה מגודל המקור, ועוד רזרבה
DISK_FACTOR = float(os.getenv("DISK_FACTOR") or 2.5)
DISK_RESERVE_GB = float(os.getenv("DISK_RESERVE_GB") or 3.0)
NICE = _int("NICE", 15)

WORK_DIR = Path(os.getenv("WORK_DIR") or "/tmp/zovexsub")

# הורדה מקישור. ברירת המחדל מעדיפה 1080p ומטה, כדי לא לגרור 4K מיותר
FETCH_FORMAT = os.getenv(
    "FETCH_FORMAT",
    "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
)
FETCH_CONNECTIONS = _int("FETCH_CONNECTIONS", 4)

# כמה בקשות במקביל מול טלגרם בהורדה ובהעלאה. יותר מדי יגרור הגבלת קצב
TG_CONNECTIONS = _int("TG_CONNECTIONS", 4)

# מגבלת גודל לקובץ שנשלח ל-Groq (25MB בתוכנית החינמית). נשאיר שולי ביטחון.
STT_CHUNK_BYTES = 20 * 1024 * 1024
# אודיו FLAC 16kHz מונו ~ 100KB לשנייה במקרה הגרוע; נחתוך לפי זמן כגיבוי
STT_CHUNK_SECONDS = _int("STT_CHUNK_SECONDS", 600)

# כמה כתוביות חשודות מותר לשמוע שוב בעבודה אחת. כל הקשבה חוזרת היא
# קריאת API נוספת, קצרה וזולה, אבל בסרט ארוך זה מצטבר
REALIGN_MAX = _int("REALIGN_MAX", 60)

# עיצוב כתוביות
SRT_MAX_CHARS_PER_LINE = _int("SRT_MAX_CHARS_PER_LINE", 42)
SRT_MAX_LINES = 2
SRT_MIN_DURATION = 1.0
SRT_MAX_DURATION = 7.0


def validate() -> list[str]:
    problems = []
    if not TG_API_ID or not TG_API_HASH:
        problems.append("חסר TG_API_ID / TG_API_HASH")
    if not GROQ_API_KEYS:
        problems.append("חסר GROQ_API_KEYS")
    if not GEMINI_API_KEYS:
        problems.append("חסר GEMINI_API_KEYS")
    return problems
