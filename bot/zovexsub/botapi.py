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
_storage = None            # ישות הערוץ, נפתרת פעם אחת


def have_bot() -> bool:
    return _bot is not None


def bot() -> TelegramClient | None:
    return _bot


async def start(premium: TelegramClient) -> None:
    """מעלה את הבוט ואת החשבון הרגיל, אם הוגדרו."""
    global _bot, _lite
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
        _lite = await _connect(StringSession(config.TG_STRING_LITE),
                               label="חשבון רגיל (מחרוזת)")
    elif config.TG_SESSION_LITE:
        _lite = await _connect(config.TG_SESSION_LITE, label="חשבון רגיל")
    if _lite is None:
        log.info("אין חשבון רגיל — כל ההעלאות דרך חשבון ה-Premium")


async def _connect(session, *, bot_token: str = "",
                   label: str = "") -> TelegramClient | None:
    candidate = TelegramClient(session, config.TG_API_ID, config.TG_API_HASH)
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
    global _bot, _lite, _storage
    for client in (_bot, _lite):
        if client is not None:
            try:
                await client.disconnect()
            except Exception as exc:  # noqa: BLE001
                log.debug("ניתוק נכשל: %s", exc)
    _bot, _lite, _storage = None, None, None


def uploader(size: int, premium: TelegramClient):
    """מי מעלה קובץ בגודל הזה.

    ההחלטה לפי הגודל בפועל, כי זו המגבלה שתפיל את ההעלאה. חשבון רגיל
    מעלה עד 2GB; מעבר לכך נדרש Premium.
    """
    if _lite is not None and size <= config.LITE_UPLOAD_MAX:
        return _lite, "רגיל"
    return premium, "Premium"


async def storage(client: TelegramClient):
    """ערוץ האחסון שאליו מעלים ושממנו הבוט מעביר."""
    global _storage
    if _storage is None and config.STORAGE_CHAT:
        target = config.STORAGE_CHAT
        _storage = await client.get_input_entity(
            int(target) if str(target).lstrip("-").isdigit() else target)
    return _storage


def ready_for_relay() -> bool:
    """האם אפשר להעביר דרך הבוט, או שצריך לשלוח ישירות כמו קודם."""
    return _bot is not None and bool(config.STORAGE_CHAT)
