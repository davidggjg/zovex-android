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
# כמה קטעים לתמלל במקביל. 0 = לפי מספר המפתחות. כל קטע תופס מפתח אחר,
# ולכן זה מנצל את כולם במקום להשאיר ארבעה בטלים
STT_PARALLEL = _int("STT_PARALLEL", 0)
# כש-Groq נכשל על קטע, לתת ל-Gemini לתמלל אותו. התזמונים שלו פחות
# מדויקים, אבל ההקשבה החוזרת וההצמדה לדיבור מתקנות אותם
GEMINI_FALLBACK_STT = (os.getenv("GEMINI_FALLBACK_STT", "1") or "1") not in ("0", "false", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-pro-latest")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-flash-latest")
GEMINI_LAST_RESORT_MODEL = os.getenv("GEMINI_LAST_RESORT_MODEL", "gemini-flash-lite-latest")
# כמה חלונות תרגום במקביל. כל חלון עומד בפני עצמו — ההקשר שלו נלקח
# מהמקור ולא מתרגום קודם — ולכן אפשר להריץ אותם במקביל
TRANSLATE_PARALLEL = _int("TRANSLATE_PARALLEL", 0)
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
    # קידוד מהיר ככל האפשר, לסרטונים קצרים בלבד. נמדד על מקור גרעיני:
    # 1.53x מול 0.98x של H.265 — חיסכון קטן בזמן — אבל 632MB מול 21MB
    "quick": {"codec": "libx264", "preset": "ultrafast", "crf": 23,
              "pix_fmt": "yuv420p", "tune": "", "mbps": 7.0},
    # H.264 — נתמך בכל מקום
    "fast": {"codec": "libx264", "preset": "veryfast", "crf": 28,
             "pix_fmt": "yuv420p", "tune": "", "mbps": 2.2},
    # H.265 — כמחצית הגודל, נתמך בטלגרם וברוב המכשירים המודרניים
    "balanced": {"codec": "libx265", "preset": "veryfast", "crf": 30,
                 "pix_fmt": "yuv420p", "tune": "", "mbps": 1.2},
    # H.265 עם preset איטי יותר — אותה איכות, קובץ קטן יותר, פי שניים מעבד
    "small": {"codec": "libx265", "preset": "medium", "crf": 30,
              "pix_fmt": "yuv420p", "tune": "", "mbps": 1.0},
}

# auto בוחר פרופיל לפי גודל המקור: קובץ קטן לא צריך דחיסה כבדה, כי גם
# פלט גדול פי כמה נשאר הרחק מתחת למגבלת ההעלאה. קובץ גדול כן צריך.
BURN_PROFILE = (os.getenv("BURN_PROFILE") or "auto").strip().lower()
# הסף נמוך בכוונה. נמדד שקידוד מהיר חוסך רק כשליש מזמן הקידוד אבל מנפח
# את הפלט פי עשרות, וההעלאה של קובץ כזה עולה יותר ממה שנחסך — ובשרת
# סטרימינג גם גוזלת רוחב פס מהמשתמשים
QUICK_UNDER_MB = _int("QUICK_UNDER_MB", 300)
SMALL_OVER_MB = _int("SMALL_OVER_MB", 3072)


# סדר יורד של מהירות: הראשון הכי מהיר, האחרון הכי דחוס
LADDER = ("quick", "balanced", "small")


def profile_for(source_bytes: int, duration: float = 0.0) -> dict:
    """בוחר הגדרות צריבה: מהירות כשאפשר, דחיסה כשחייבים.

    מקור קטן לא צריך דחיסה כבדה — גם פלט גדול פי כמה נשאר הרחק מתחת
    למגבלת ההעלאה, וחבל לבזבז עליו זמן מעבד. מקור גדול כן צריך.
    אחרי הבחירה נבדק שהפלט הצפוי נכנס במגבלה, ואם לא יורדים דרגה.
    """
    if BURN_PROFILE != "auto":
        return PROFILES.get(BURN_PROFILE, PROFILES["balanced"])

    megabytes = source_bytes / 1024 ** 2
    if megabytes <= QUICK_UNDER_MB:
        start = 0
    elif megabytes >= SMALL_OVER_MB:
        start = 2
    else:
        start = 1

    for name in LADDER[start:]:
        settings = PROFILES[name]
        if duration <= 0:
            return settings
        predicted = settings["mbps"] * 1_000_000 * duration / 8 / 1024 ** 2
        if predicted <= UPLOAD_CEILING_MB:
            return settings
    return PROFILES["small"]


def profile_name(settings: dict) -> str:
    for name, values in PROFILES.items():
        if values is settings:
            return name
    return BURN_PROFILE


_profile = PROFILES.get(BURN_PROFILE, PROFILES["balanced"])

# דריסות נקודתיות. ריק פירושו "לפי הפרופיל שנבחר לקובץ"
BURN_CODEC = os.getenv("BURN_CODEC", "")
BURN_PRESET = os.getenv("BURN_PRESET", "")
BURN_CRF = os.getenv("BURN_CRF", "")
BURN_PIX_FMT = os.getenv("BURN_PIX_FMT", "")
BURN_TUNE = os.getenv("BURN_TUNE", "")

# תקרת bitrate קשיחה מעוותת את האיכות: סצנה מורכבת נחנקת בדיוק כשהיא
# צריכה ביטים. CRF לבדו מחלק את הביטים נכון, ולכן התקרה כבויה כברירת
# מחדל. ערך גדול מאפס מפעיל אותה, למקרה שחייבים להיכנס בגודל מסוים.
UPLOAD_LIMIT_MB = _int("UPLOAD_LIMIT_MB", 0)
# קרדיט שמוצג בפתיחת הסרטון הצרוב. שורות מופרדות בתו |, ריק מבטל
CREDIT_TEXT = os.getenv("CREDIT_TEXT", "עלה וקודד על ידי|zovex|ומלך הדרמות הטורקיות")
CREDIT_SECONDS = float(os.getenv("CREDIT_SECONDS") or 10)
CREDIT_SIZE = _int("CREDIT_SIZE", 34)

# תקרת ההעלאה של טלגרם פרימיום, לבחירת פרופיל בלבד (לא תקרת bitrate)
UPLOAD_CEILING_MB = _int("UPLOAD_CEILING_MB", 3800)
# תקרת רזולוציה. המקור אף פעם לא מוגדל — רק 4K וגבוה מזה יורד ל-1080p,
# כדי שהצריבה לא תימשך נצח. 0 מבטל כל שינוי רזולוציה.
BURN_MAX_HEIGHT = _int("BURN_MAX_HEIGHT", 1080)
FFMPEG_THREADS = _int("FFMPEG_THREADS", 1)
# לצריבה כדאי יותר מ-thread אחד: הצוואר הוא פענוח המקור, ושתי ליבות
# מכפילות את המהירות פי 2.4 בלי לשנות את גודל הפלט.
#
# auto קובע את המספר לפי העומס בפועל ברגע שהצריבה מתחילה: בשעה שקטה
# הוא לוקח כמעט את כל הליבות, ובשעת עומס מצטמצם. מעבר לזה, nice ו-ionice
# דואגים שגם כשהצריבה רצה על הרבה ליבות, כל תהליך אחר דוחק אותה מיד.
BURN_THREADS = os.getenv("BURN_THREADS", "auto").strip().lower()
# כמה ליבות להשאיר פנויות לשאר השרת גם כשהוא נראה ריק
RESERVE_CORES = float(os.getenv("RESERVE_CORES") or 1.5)
# תקרה עליונה ל-threads, 0 = עד כל הליבות
BURN_THREADS_MAX = _int("BURN_THREADS_MAX", 0)
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


def parallel(setting: int, keys: list[str], ceiling: int = 8) -> int:
    """כמה בקשות במקביל: לפי ההגדרה, או לפי מספר המפתחות שיש."""
    if setting > 0:
        return setting
    return max(1, min(len(keys) or 1, ceiling))


def validate() -> list[str]:
    problems = []
    if not TG_API_ID or not TG_API_HASH:
        problems.append("חסר TG_API_ID / TG_API_HASH")
    if not GROQ_API_KEYS:
        problems.append("חסר GROQ_API_KEYS")
    if not GEMINI_API_KEYS:
        problems.append("חסר GEMINI_API_KEYS")
    return problems
