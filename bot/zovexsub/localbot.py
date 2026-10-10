"""שליחה דרך שרת Bot API מקומי.

למה לא הבוט הרגיל: בוט מוגבל לכ-50MB מול השרתים הציבוריים של טלגרם —
גם דרך MTProto. זו מגבלה על חשבון הבוט עצמו ולא על הפרוטוקול.

שרת Bot API מקומי שרץ אצלנו מעלה את התקרה ל-2GB, ומאפשר לבוט לקרוא
קובץ מנתיב בדיסק במקום להעלות אותו ב-HTTP. באותו שרת זה כמעט מיידי.

מעל 2GB גם זה לא עוזר — שם נדרש חשבון Premium, ולכן הפלט הגדול ממשיך
לעבור דרך חשבון המשתמש.
"""
from __future__ import annotations

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
