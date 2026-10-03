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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-pro-latest")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-flash-latest")
GEMINI_LAST_RESORT_MODEL = os.getenv("GEMINI_LAST_RESORT_MODEL", "gemini-flash-lite-latest")
# מעבר החקר לא קריטי — אחריו ממשיכים בלעדיו במקום להחזיק את התור
RESEARCH_TIMEOUT = _int("RESEARCH_TIMEOUT", 180)

MAX_INPUT_MINUTES = _int("MAX_INPUT_MINUTES", 180)
BURN_MAX_MINUTES = _int("BURN_MAX_MINUTES", 10)
BURN_PRESET = os.getenv("BURN_PRESET", "veryfast")
BURN_CRF = _int("BURN_CRF", 28)
BURN_MAX_HEIGHT = _int("BURN_MAX_HEIGHT", 720)
FFMPEG_THREADS = _int("FFMPEG_THREADS", 1)
# תקרה קשיחה לצריבה. תוכן גרעיני מקודד לאט מזמן אמת, ובלי תקרה קובץ
# חריג יכול לרוץ שעה על שרת עמוס
BURN_TIMEOUT = _int("BURN_TIMEOUT", 1800)
# בדיקת מקום בדיסק לפני הורדה וצריבה: פי כמה מגודל המקור, ועוד רזרבה
DISK_FACTOR = float(os.getenv("DISK_FACTOR") or 2.5)
DISK_RESERVE_GB = float(os.getenv("DISK_RESERVE_GB") or 3.0)
NICE = _int("NICE", 15)

WORK_DIR = Path(os.getenv("WORK_DIR") or "/tmp/zovexsub")

# מגבלת גודל לקובץ שנשלח ל-Groq (25MB בתוכנית החינמית). נשאיר שולי ביטחון.
STT_CHUNK_BYTES = 20 * 1024 * 1024
# אודיו FLAC 16kHz מונו ~ 100KB לשנייה במקרה הגרוע; נחתוך לפי זמן כגיבוי
STT_CHUNK_SECONDS = _int("STT_CHUNK_SECONDS", 600)

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
