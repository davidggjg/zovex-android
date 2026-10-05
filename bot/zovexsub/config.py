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
# גודל הכתוביות: קטן / בינוני / גדול. אפשר לבחור גם לכל צריבה בנפרד
SUB_SIZE = (os.getenv("SUB_SIZE") or "קטן").strip()
SUB_FONT = os.getenv("SUB_FONT", "Noto Sans Hebrew")
CREDIT_TEXT = os.getenv("CREDIT_TEXT", "עלה וקודד על ידי|zovex|ועולם הדרמות הטורקיות")
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
# תקרה קשיחה לצריבה. ערך קבוע לא מתאים: חצי שעה מספיקה לסרטון קצר אבל
# הורגת סרט של שעתיים ממש לפני הסוף. auto גוזר אותה מאורך הווידאו לפי
# הקצב האיטי ביותר שנמדד, עם רצפה ושוליים
BURN_TIMEOUT = os.getenv("BURN_TIMEOUT", "auto").strip().lower()
BURN_TIMEOUT_FACTOR = float(os.getenv("BURN_TIMEOUT_FACTOR") or 4.0)
BURN_TIMEOUT_FLOOR = _int("BURN_TIMEOUT_FLOOR", 1800)

# צריבה מקבילית. מסנן הכתוביות של ffmpeg רץ בחוט אחד, ולכן תהליך יחיד
# לא מצליח להעסיק מכונה עם הרבה ליבות. חיתוך הווידאו לקטעים והרצת
# תהליך לכל קטע נותנת צינור רינדור נפרד לכל אחד.
#
# כמה חוטים לתת לכל קטע? נמדד על מקור גרעיני 1080p, תהליך אחד, אותן
# הגדרות קידוד שבפרודקשן:
#   חוט אחד   0.17x   (0.170 לליבה)
#   שני חוטים 0.35x   (0.175 לליבה)  ← היעיל ביותר
#   שלושה     0.47x   (0.157 לליבה)
#   ארבעה     0.58x   (0.145 לליבה)
# התשואה לכל ליבה יורדת כבר מהחוט השלישי, ולכן עדיף יותר תהליכים עם
# פחות חוטים: 9 קטעים של שני חוטים מוציאים כ-12% יותר מ-6 של שלושה.
# אורך הקטע קובע את צפיפות החלוקה מחדש של הליבות. קטע ארוך מחזיק את
# המקום שלו עד שהוא נגמר, ואז צריבה שנייה פשוט ממתינה לראשונה במקום
# להתחלק איתה. קטעים קצרים משחררים מקום כל הזמן, וכך החלוקה אמיתית.
# שתי דקות: פתיחת ffmpeg (כחצי שנייה) זניחה מול הקידוד עצמו
BURN_CHUNK_SECONDS = _int("BURN_CHUNK_SECONDS", 120)
BURN_SEGMENT_THREADS = _int("BURN_SEGMENT_THREADS", 2)
BURN_CHUNKS_MAX = _int("BURN_CHUNKS_MAX", 200)


def burn_chunks(duration: float) -> int:
    """לכמה קטעים לחתוך וידאו באורך הזה."""
    return max(1, min(BURN_CHUNKS_MAX,
                      -(-int(duration) // max(1, BURN_CHUNK_SECONDS))))
# וידאו קצר לא מרוויח מהפיצול, ורק מסבך
BURN_PARALLEL_MIN_MINUTES = _int("BURN_PARALLEL_MIN_MINUTES", 3)
# כמה צריבות מותר להריץ בו-זמנית. מעבר לזה נכנסים לתור
BURN_JOBS = _int("BURN_JOBS", 2)


def burn_slots(cores: int) -> int:
    """כמה קטעים מותר להריץ בו-זמנית בכל המכונה, על פני כל הצריבות.

    זה מה שמחלק את הליבות בין צריבות מקבילות, ובלי לשנות שום תהליך
    שכבר רץ: הקטעים הם שמתחרים על המקומות. צריבה לבדה תופסת את כולם
    ומקבלת את המכונה כולה; כששנייה מצטרפת הן מתחלקות מאליהן, וכשאחת
    מסיימת השנייה מתרחבת בחזרה בלי שאיש יתערב.
    """
    return max(1, cores // max(1, BURN_SEGMENT_THREADS))


def burn_timeout(duration: float) -> float:
    """כמה זמן לתת לצריבה של וידאו באורך הזה."""
    setting = str(BURN_TIMEOUT)
    if setting.isdigit():
        return float(setting)
    return max(float(BURN_TIMEOUT_FLOOR), duration * BURN_TIMEOUT_FACTOR)
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
# יוטיוב חוסם הורדות משרתים ודורש התחברות. קובץ עוגיות בפורמט Netscape
# מחשבון מחובר פותר את זה. ריק = בלי עוגיות
FETCH_COOKIES = os.getenv("FETCH_COOKIES", "")
# cobalt — שרת הורדה קטן שרץ אצלנו בקונטיינר. יוטיוב חוסמים את yt-dlp
# משרתים, ו-cobalt מותקן עצמית עוקף את זה. ריק = משתמשים רק ב-yt-dlp
COBALT_URL = (os.getenv("COBALT_URL") or "").rstrip("/")
COBALT_QUALITY = os.getenv("COBALT_QUALITY", "1080")
# aria2c מוריד בכמה חיבורים מקבילים ומנצל את הקו טוב יותר מההורדה
# הפנימית של yt-dlp. ריק = לא בשימוש
FETCH_ARIA2 = (os.getenv("FETCH_ARIA2") or "auto").strip().lower()
ARIA2_CONNECTIONS = _int("ARIA2_CONNECTIONS", 16)

# כמה בקשות במקביל מול טלגרם בהורדה ובהעלאה. יותר מדי יגרור הגבלת קצב
TG_CONNECTIONS = _int("TG_CONNECTIONS", 8)
# תקרות זמן למסלול המהיר. בלעדיהן חיבור שלא עונה תוקע את העבודה לנצח
# במקום ליפול חזרה למסלול הרגיל של טלתון
TG_CONNECT_TIMEOUT = float(os.getenv("TG_CONNECT_TIMEOUT") or 45)
# תקרת זמן לבקשת חלק בודדת. בלעדיה חיבור שמפסיק לענות באמצע משאיר את
# העובד שלו ממתין לנצח, וההורדה נתקעת באחוז אקראי בלי שגיאה
TG_READ_TIMEOUT = float(os.getenv("TG_READ_TIMEOUT") or 60)
TG_READ_RETRIES = _int("TG_READ_RETRIES", 3)
# אם לא ירד אף בייט בפרק הזמן הזה, ההעברה מוכרזת תקועה ונופלת חזרה
TG_STALL_TIMEOUT = float(os.getenv("TG_STALL_TIMEOUT") or 180)
TG_FAST_TIMEOUT = float(os.getenv("TG_FAST_TIMEOUT") or 0)   # 0 = בלי תקרה

# מגבלת גודל לקובץ שנשלח ל-Groq (25MB בתוכנית החינמית). נשאיר שולי ביטחון.
STT_CHUNK_BYTES = 20 * 1024 * 1024
# אודיו FLAC 16kHz מונו ~ 100KB לשנייה במקרה הגרוע; נחתוך לפי זמן כגיבוי
STT_CHUNK_SECONDS = _int("STT_CHUNK_SECONDS", 600)
# אורך מינימלי לחלק. חלק קצר מדי פוגע בהקשר שהמודל רואה
STT_CHUNK_MIN_SECONDS = _int("STT_CHUNK_MIN_SECONDS", 150)

# כמה כתוביות חשודות מותר לשמוע שוב בעבודה אחת. כל הקשבה חוזרת היא
# קריאת API נוספת, קצרה וזולה, אבל בסרט ארוך זה מצטבר
REALIGN_MAX = _int("REALIGN_MAX", 60)

# עיצוב כתוביות
SRT_MAX_CHARS_PER_LINE = _int("SRT_MAX_CHARS_PER_LINE", 42)
SRT_MAX_LINES = 2
SRT_MIN_DURATION = 1.0
SRT_MAX_DURATION = 7.0


# תקרה עליונה למקביליות, לא משנה כמה מפתחות יש
PARALLEL_CEILING = _int("PARALLEL_CEILING", 16)


def parallel(setting: int, keys: list[str], ceiling: int = 0) -> int:
    """כמה בקשות במקביל: לפי ההגדרה, או לפי מספר המפתחות שיש.

    כל מפתח הוא חשבון נפרד עם מכסה משלו, ולכן יותר מפתחות פירושם יותר
    עבודה בו-זמנית ולא רק גיבוי.
    """
    if setting > 0:
        return setting
    return max(1, min(len(keys) or 1, ceiling or PARALLEL_CEILING))


def validate() -> list[str]:
    problems = []
    if not TG_API_ID or not TG_API_HASH:
        problems.append("חסר TG_API_ID / TG_API_HASH")
    if not GROQ_API_KEYS:
        problems.append("חסר GROQ_API_KEYS")
    if not GEMINI_API_KEYS:
        problems.append("חסר GEMINI_API_KEYS")
    return problems


# זיהוי דיבור. silencedetect מודד עוצמה ולכן סופר מוזיקת רקע כדיבור;
# מודל VAD אמיתי מבדיל ביניהם. ריק או קובץ חסר = חוזרים לשיטה הישנה
VAD_MODEL = os.getenv("VAD_MODEL") or "/opt/zovexsub/models/silero_vad.onnx"
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD") or 0.5)
# ריפוד סביב כל קטע דיבור, כדי לא לחתוך הברה ראשונה או אחרונה
VAD_PAD = float(os.getenv("VAD_PAD") or 0.15)
# פער קצר בין שני קטעים הוא נשימה באמצע משפט, לא סוף דיבור
VAD_JOIN = float(os.getenv("VAD_JOIN") or 0.35)
VAD_MIN_SPEECH = float(os.getenv("VAD_MIN_SPEECH") or 0.20)
