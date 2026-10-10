"""שליחה דרך שרת Bot API מקומי.

למה לא הבוט הרגיל: בוט מוגבל לכ-50MB מול השרתים הציבוריים של טלגרם —
גם דרך MTProto. זו מגבלה על חשבון הבוט עצמו ולא על הפרוטוקול.

שרת Bot API מקומי שרץ אצלנו מעלה את התקרה ל-2GB, ומאפשר לבוט לקרוא
קובץ מנתיב בדיסק במקום להעלות אותו ב-HTTP. באותו שרת זה כמעט מיידי.

מעל 2GB גם זה לא עוזר — שם נדרש חשבון Premium, ולכן הפלט הגדול ממשיך
לעבור דרך חשבון המשתמש.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from . import config

log = logging.getLogger(__name__)

# מעבר לזה אין טעם לנסות: השרת המקומי עצמו לא עובר את התקרה הזאת
MAX_BYTES = 2000 * 1024 * 1024


def available() -> bool:
    return bool(config.BOT_TOKEN and config.BOT_API_URL)


def _url(method: str) -> str:
    return f"{config.BOT_API_URL.rstrip('/')}/bot{config.BOT_TOKEN}/{method}"


async def call(method: str, **fields) -> dict:
    """קריאה אחת לשרת המקומי. מחזירה את ה-result או זורקת."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0)) as web:
        reply = await web.post(_url(method), data=fields)
    body = reply.json()
    if not body.get("ok"):
        raise RuntimeError(f"{method}: {body.get('description', reply.text[:200])}")
    return body.get("result") or {}


async def probe() -> str:
    """מוודא שהשרת חי ושהטוקן תקף. מחזיר את שם הבוט."""
    me = await call("getMe")
    return me.get("username") or str(me.get("id", ""))


async def send_video(chat_id, path: Path, *, caption: str = "",
                     duration: int = 0, width: int = 0, height: int = 0,
                     thumb: Path | None = None) -> dict:
    """שולח וידאו מנתיב מקומי.

    במצב --local השרת קורא את הקובץ מהדיסק ישירות, ולכן אין כאן העלאה
    ב-HTTP בכלל — רק מסירת הנתיב. זה ההבדל המעשי מול השרת הציבורי.
    """
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise RuntimeError(
            f"{size / 1024 ** 3:.2f}GB מעל תקרת הבוט — נדרש חשבון Premium")
    fields = {
        "chat_id": str(chat_id),
        "video": path.resolve().as_uri(),      # file:// — בלי העלאה
        "caption": caption,
        "supports_streaming": "true",
    }
    for name, value in (("duration", int(duration)),
                        ("width", int(width)), ("height", int(height))):
        if value:
            fields[name] = str(value)
    if thumb and thumb.exists():
        fields["thumbnail"] = thumb.resolve().as_uri()
    log.info("שולח %.0fMB דרך השרת המקומי", size / 1048576)
    return await call("sendVideo", **fields)


async def find_chat() -> list[dict]:
    """מי כבר לחץ /start אצל הבוט.

    בוט אינו יכול לפתוח שיחה — רק לענות למי שפנה אליו. לכן צריך את
    מזהה הצ'אט, והדרך להשיג אותו היא לקרוא את העדכונים האחרונים.
    """
    found: dict[int, dict] = {}
    for update in await call("getUpdates", limit=100, timeout=0):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if chat.get("id"):
            found[chat["id"]] = chat
    return list(found.values())


def keyboard(rows: list[list[tuple[str, str]]]) -> str:
    """מקלדת כפתורים. כל כפתור הוא (טקסט, ערך שיחזור בלחיצה)."""
    return json.dumps({"inline_keyboard": [
        [{"text": text, "callback_data": data} for text, data in row]
        for row in rows
    ]}, ensure_ascii=False)


async def say(chat_id, text: str, *, buttons: str = "",
              reply_to: int = 0) -> dict:
    fields = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML"}
    if buttons:
        fields["reply_markup"] = buttons
    if reply_to:
        fields["reply_to_message_id"] = str(reply_to)
    return await call("sendMessage", **fields)


async def edit(chat_id, message_id: int, text: str,
               *, buttons: str = "") -> dict:
    """עורך הודעה קיימת. כך שאלה הופכת לשאלה הבאה בלי להציף את הצ'אט."""
    fields = {"chat_id": str(chat_id), "message_id": str(message_id),
              "text": text, "parse_mode": "HTML"}
    fields["reply_markup"] = buttons or json.dumps({"inline_keyboard": []})
    try:
        return await call("editMessageText", **fields)
    except RuntimeError as exc:
        # טלגרם דוחה עריכה לטקסט זהה. זה לא כשל אמיתי
        if "not modified" in str(exc).lower():
            return {}
        raise


async def tap(callback_id: str, note: str = "") -> None:
    """מאשר ללחיצה. בלי זה הכפתור נשאר עם סמן טעינה מסתובב."""
    fields = {"callback_query_id": callback_id}
    if note:
        fields["text"] = note
    try:
        await call("answerCallbackQuery", **fields)
    except RuntimeError as exc:
        log.debug("אישור לחיצה נכשל: %s", exc)


async def updates(offset: int, timeout: int = 25) -> list[dict]:
    """משיכת עדכונים ארוכה. timeout בצד השרת חוסך סיבובים מיותרים."""
    return await call("getUpdates", offset=offset, timeout=timeout,
                      allowed_updates=json.dumps(["message", "callback_query"]))


async def local_path(file_id: str) -> Path | None:
    """הנתיב בדיסק של קובץ שנשלח לבוט.

    זה היתרון הגדול של השרת המקומי, ולא רק בהעלאה: במצב --local הוא
    שומר את הקובץ הנכנס אצלו, ו-getFile מחזיר נתיב מוחלט במקום כתובת
    להורדה. כלומר סרטון שנשלח לבוט כבר נמצא על הדיסק — אין מה להוריד
    מטלגרם, וכל שאלת מהירות ההורדה פשוט לא רלוונטית למסלול הזה.
    """
    try:
        info = await call("getFile", file_id=file_id)
    except RuntimeError as exc:
        log.warning("getFile נכשל: %s", exc)
        return None
    raw = info.get("file_path") or ""
    if not raw:
        return None
    found = Path(raw)
    if not found.is_absolute():
        # שרת ציבורי מחזיר נתיב יחסי להורדה, ולא קובץ מקומי
        log.info("הקובץ אינו מקומי (%s) — השרת כנראה אינו במצב --local", raw)
        return None
    if not found.exists():
        log.warning("getFile הצביע על %s שאינו קיים", found)
        return None
    return found


def media_of(message: dict) -> tuple[str, int, str]:
    """מחלץ (file_id, גודל, שם) מהודעה, או ריק כשאין מדיה."""
    for key in ("video", "document", "animation"):
        item = message.get(key)
        if item:
            return (item.get("file_id", ""),
                    int(item.get("file_size", 0) or 0),
                    item.get("file_name", "") or f"{key}.mp4")
    return "", 0, ""
