"""הבוט כממשק, ושני חשבונות משתמש כמנועי ההעברה.

חלוקת התפקידים:
  הבוט            — כפתורים, הודעות, קבלת בקשות. לא מעלה קבצים.
  חשבון רגיל      — מעלה פלט עד 2GB.
  חשבון Premium   — מעלה פלט מעל 2GB.

למה לא שהבוט יעלה: ה-Bot API חוסם העלאה הרבה מתחת למה שאנחנו מפיקים.
למה חשבון לא יכול לשלוח ישירות: צ'אט פרטי בין אדם לבוט אינו נגיש
לחשבון משתמש — אי אפשר לכתוב לתוכו.

לכן ערוץ אחסון באמצע: החשבון מעלה אליו, והבוט מעביר משם אל המשתמש.
העברה אינה העלאה — הקובץ כבר אצל טלגרם — ולכן שום מגבלת גודל של הבוט
אינה חלה עליה. זה המבנה שבו משתמשים בוטים לקבצים גדולים.
"""
from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.sessions import StringSession

from . import config

log = logging.getLogger(__name__)

_bot: TelegramClient | None = None
_lite: TelegramClient | None = None
_premium: TelegramClient | None = None
# ישות הערוץ לכל חשבון בנפרד. access_hash של ערוץ הוא ייחודי לחשבון,
# ולכן peer שחשבון אחד פתר אינו תקף אצל אחר — טלגרם עונה "invalid
# Peer". מטמון יחיד גרם בדיוק לזה: ההורדה פתרה עם החשבון הרגיל,
# וההעלאה קיבלה את הישות שלו במקום של Premium
_storage: dict[int, object] = {}


def premium() -> TelegramClient | None:
    """חשבון ה-Premium, לשימוש מסלולים שאין להם את האירוע המקורי."""
    return _premium


def lite() -> TelegramClient | None:
    """החשבון הרגיל. קיים גם כשאין Premium, ולרוב הוא היחיד שמחובר."""
    return _lite


def have_bot() -> bool:
    return _bot is not None


def bot() -> TelegramClient | None:
    return _bot


async def start(premium: TelegramClient) -> None:
    """מעלה את הבוט ואת החשבון הרגיל, אם הוגדרו."""
    global _bot, _lite, _premium
    _premium = premium
    if config.BOT_TOKEN:
        _bot = await _connect(f"{config.TG_SESSION}-bot",
                              bot_token=config.BOT_TOKEN, label="בוט")
    else:
        log.info("אין טוקן בוט — ממשק הכפתורים מושבת")

    # מחרוזת סשן עדיפה על קובץ: היא נוצרת פעם אחת עם טלפון וקוד, ואחר
    # כך היא רק שורה ב-.env — בלי התחברות אינטראקטיבית בשרת ובלי קובץ
    # שצריך להעתיק. זה מה שבוטים אחרים עושים, ומה שנראה כאילו הכל
    # מחובר דרך הטוקן
    if config.TG_STRING_LITE:
        # כשל כאן לא מפיל את השירות: החשבון השני הוא תוספת, והבוט
        # הראשי חייב לעלות גם בלעדיו
        try:
            _lite = await _connect(_string_session(config.TG_STRING_LITE),
                                   label="חשבון רגיל (מחרוזת)")
        except Exception as exc:  # noqa: BLE001
            log.error("%s — ממשיכים בלי החשבון השני", exc)
    elif config.TG_SESSION_LITE:
        _lite = await _connect(config.TG_SESSION_LITE, label="חשבון רגיל")
    if _lite is None:
        log.info("אין חשבון רגיל — כל ההעלאות דרך חשבון ה-Premium")


def _string_session(raw: str):
    """בונה סשן ממחרוזת, וסולח לטעויות העתקה נפוצות.

    המחרוזת מודפסת כשורה שלמה בצורת TG_STRING_LITE=..., וקל להעתיק את
    כולה כולל השם — ואז נוצר בקובץ ערך כפול. טלתון זורק על זה
    "Not a valid string", והשירות נכנס ללולאת קריסה שבה השגיאה האמיתית
    נבלעת בין הודעות ההפעלה מחדש של systemd. עדיף לנקות ולהמשיך
    """
    value = raw.strip().strip('"').strip("'")
    while "=" in value and value.split("=", 1)[0].isidentifier():
        value = value.split("=", 1)[1].strip()
    try:
        return StringSession(value)
    except ValueError as exc:
        raise RuntimeError(
            f"TG_STRING_LITE אינו מחרוזת סשן תקינה ({exc}). "
            f"אורך שהתקבל: {len(value)}, צפוי כ-350. "
            "ליצירה מחדש: python3 tests/mksession.py") from exc


async def _connect(session, *, bot_token: str = "",
                   label: str = "") -> TelegramClient | None:
    # לבוט: בלי קבלת עדכונים. טלגרם מתיר צרכן עדכונים אחד בלבד לכל
    # טוקן, ושרת ה-Bot API המקומי כבר ממלא את התפקיד הזה. לקוח שני
    # שמבקש עדכונים לאותו טוקן נאבק איתו, ושתי הסשנים מנתקים זה את
    # זה שוב ושוב — זו לולאת ההתחברות מחדש שנראתה בלוג, וזה מקור
    # ה-"Server disconnected without sending a response" בהורדה.
    # בלי עדכונים הלקוח משמש רק להעברת קבצים, ואין על מה להתנגש
    extra = {"receive_updates": False} if bot_token else {}
    candidate = TelegramClient(session, config.TG_API_ID, config.TG_API_HASH,
                               **extra)
    try:
        if bot_token:
            await candidate.start(bot_token=bot_token)
        else:
            await candidate.connect()
            if not await candidate.is_user_authorized():
                raise RuntimeError(
                    "הסשן אינו מחובר. ליצירת מחרוזת סשן חד-פעמית: "
                    "python3 bot/tests/mksession.py")
        me = await candidate.get_me()
    except Exception as exc:  # noqa: BLE001 — חיבור שבור לא מפיל את השירות
        log.error("%s לא התחבר (%s) — ממשיכים בלעדיו", label, exc)
        try:
            await candidate.disconnect()
        except Exception as inner:  # noqa: BLE001
            log.debug("ניתוק אחרי כשל נכשל: %s", inner)
        return None
    log.info("%s מחובר: %s (id=%s)", label,
             getattr(me, "username", None) or me.first_name, me.id)
    return candidate


async def stop() -> None:
    global _bot, _lite, _premium
    for client in (_bot, _lite):
        if client is not None:
            try:
                await client.disconnect()
            except Exception as exc:  # noqa: BLE001
                log.debug("ניתוק נכשל: %s", exc)
    _storage.clear()
    _bot, _lite, _premium = None, None, None


def uploader(size: int, premium: TelegramClient):
    """מי מעלה קובץ בגודל הזה.

    ההחלטה לפי הגודל בפועל, כי זו המגבלה שתפיל את ההעלאה. חשבון רגיל
    מעלה עד 2GB; מעבר לכך נדרש Premium.
    """
    if _lite is not None and size <= config.LITE_UPLOAD_MAX:
        return _lite, "רגיל"
    return premium, "Premium"


def downloader(size: int, premium: TelegramClient):
    """מי מוריד קובץ בגודל הזה.

    הפיצול מוריד לחץ: כל קובץ עובר בחשבון אחד בלבד במקום ששניהם
    ייספגו את כל התנועה. ההחלטה לפי גודל המקור, שידוע מראש — להבדיל
    מההעלאה, שמנותבת לפי גודל הפלט שנודע רק אחרי הצריבה.

    חשבון יכול להוריד רק הודעה שהוא רואה. כשהחשבון הרגיל אינו בצ'אט
    שבו נשלח הסרטון ההורדה תיכשל, ולכן הקורא חייב ליפול חזרה
    """
    if _lite is not None and 0 < size <= config.LITE_UPLOAD_MAX:
        return _lite, "רגיל"
    return premium, "Premium"


async def storage(client: TelegramClient):
    """ערוץ האחסון, כפי שהחשבון הזה רואה אותו.

    המטמון לפי חשבון ולא גלובלי: ראו ההערה ליד _storage.

    ‏get_input_entity נכשל כשהחשבון עוד לא "ראה" את הערוץ בסשן הזה,
    גם כשהוא בעליו. משיכת הדיאלוגים ממלאת את המטמון הפנימי של
    טלתון, וזה התיקון המקובל לתקלה הזאת
    """
    if not config.STORAGE_CHAT:
        return None
    key = id(client)
    if key in _storage:
        return _storage[key]

    target = config.STORAGE_CHAT
    want = int(target) if str(target).lstrip("-").isdigit() else target
    try:
        found = await client.get_input_entity(want)
    except (ValueError, TypeError) as exc:
        log.info("הערוץ לא נפתר ישירות (%s) — ממלא את רשימת הצ'אטים", exc)
        try:
            await client.get_dialogs(limit=None)
            found = await client.get_input_entity(want)
        except Exception as inner:  # noqa: BLE001 — הקורא נופל אחורה
            log.warning("ערוץ האחסון %s אינו נגיש לחשבון הזה: %s",
                        target, inner)
            return None
    _storage[key] = found
    return found


def ready_for_relay() -> bool:
    """האם אפשר להעביר דרך הבוט, או שצריך לשלוח ישירות כמו קודם."""
    return _bot is not None and bool(config.STORAGE_CHAT)
