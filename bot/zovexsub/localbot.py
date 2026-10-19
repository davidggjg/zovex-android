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
import os
import shutil
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


async def call(method: str, read: float = 600.0, **fields):
    """קריאה אחת לשרת המקומי. מחזירה את ה-result או זורקת.

    read ניתן לכוונון כי לא כל הקריאות שוות: העלאת קובץ של שני ג'יגה
    מצדיקה המתנה ארוכה, אבל getMe בהפעלה לא — ושם המתנה של עשר דקות
    פירושה שירות שתקוע ולא עולה בכלל
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(read, connect=15.0)) as web:
        reply = await web.post(_url(method), data=fields)
    body = reply.json()
    if not body.get("ok"):
        raise RuntimeError(f"{method}: {body.get('description', reply.text[:200])}")
    # "or {}" הפך רשימה ריקה למילון, כלומר getUpdates בלי עדכונים החזיר
    # טיפוס אחר מ-getUpdates עם עדכונים. כאן נשמר הטיפוס כמו שהוא
    result = body.get("result")
    return {} if result is None else result


async def forward(to_chat, from_chat, message_id: int) -> dict:
    """מעביר הודעה לערוץ האחסון ומחזיר את ההודעה שנוצרה שם.

    העברה אינה העלאה — הקובץ כבר אצל טלגרם — ולכן היא מיידית גם
    לקובץ של שני ג'יגה. היא קיימת כאן בשביל ההורדה: חשבון משתמש
    אינו רואה את הצ'אט הפרטי שבין האדם לבוט, ולכן אינו יכול להוריד
    משם. בערוץ האחסון הוא כן חבר, וההודעה המועברת היא שלו לכל דבר
    """
    return await call("forwardMessage", read=120.0,
                      chat_id=str(to_chat), from_chat_id=str(from_chat),
                      message_id=str(message_id))


async def probe() -> str:
    """מוודא שהשרת חי ושהטוקן תקף. מחזיר את שם הבוט.

    תקרה קצרה בכוונה: הקריאה הזאת רצה בהפעלה, ולפניה botmenu.start
    עוד לא נקרא. אם היא תולה, הבוט לא מתחיל להאזין בכלל — ואין שום
    שורה בלוג שמסבירה למה
    """
    me = await call("getMe", read=20.0)
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
        "video": _to_container(path),          # file:// — בלי העלאה
        "caption": caption,
        "supports_streaming": "true",
    }
    for name, value in (("duration", int(duration)),
                        ("width", int(width)), ("height", int(height))):
        if value:
            fields[name] = str(value)
    if thumb and thumb.exists():
        fields["thumbnail"] = _to_container(thumb)
    log.info("שולח %.0fMB דרך השרת המקומי", size / 1048576)
    try:
        return await call("sendVideo", **fields)
    finally:
        clear_outbox(path.name)
        if thumb:
            clear_outbox(thumb.name)


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
    """משיכת עדכונים ארוכה. timeout בצד השרת חוסך סיבובים מיותרים.

    תקרת הקריאה גדולה רק במעט מהמתנת השרת: בלעדיה משיכה שלא נענית
    תולה את הלולאה עשר דקות, והבוט נראה מת בלי שום שגיאה
    """
    got = await call("getUpdates", read=timeout + 20, offset=offset,
                     timeout=timeout,
                     allowed_updates=json.dumps(["message", "callback_query"]))
    return got if isinstance(got, list) else []


async def local_path(file_id: str) -> Path | None:
    found, _ = await locate(file_id)
    return found


async def locate(file_id: str) -> tuple[Path | None, str]:
    """הנתיב בדיסק של קובץ שנשלח לבוט.

    זה היתרון הגדול של השרת המקומי, ולא רק בהעלאה: במצב --local הוא
    שומר את הקובץ הנכנס אצלו, ו-getFile מחזיר נתיב מוחלט במקום כתובת
    להורדה. כלומר סרטון שנשלח לבוט כבר נמצא על הדיסק — אין מה להוריד
    מטלגרם, וכל שאלת מהירות ההורדה פשוט לא רלוונטית למסלול הזה.
    """
    try:
        info = await call("getFile", file_id=file_id)
    except RuntimeError as exc:
        return None, f"getFile נכשל: {exc}"
    raw = info.get("file_path") or ""
    if not raw:
        return None, "getFile לא החזיר נתיב כלל"
    found = _translate(Path(raw))
    if not found.is_absolute():
        return None, (f"הנתיב שחזר יחסי ({raw}) — השרת אינו במצב --local")
    if not found.exists():
        hint = ("" if config.BOT_API_DATA else
                " · BOT_API_DATA אינו מוגדר, וכשהשרת בדוקר הוא נדרש")
        return None, f"השרת הצביע על {found} שאינו קיים{hint}"
    return found, ""


def _translate(path: Path) -> Path:
    """מתרגם נתיב מתוך הקונטיינר לנתיב במארח.

    השרת רץ בדוקר ומדווח את הנתיב כפי שהוא רואה אותו אצלו, למשל
    /var/lib/telegram-bot-api/... . הפייתון שלנו רץ על המארח, ושם אותו
    קובץ יושב בתיקייה שחוברה ב-volume. אותו קובץ, שני נתיבים — ובלי
    התרגום הזה הקריאה נכשלת בשקט ונראית כאילו השרת אינו במצב --local.
    """
    if not config.BOT_API_DATA:
        return path
    inside = config.BOT_API_INSIDE.rstrip("/")
    text = str(path)
    if inside and text.startswith(inside):
        return Path(config.BOT_API_DATA) / text[len(inside):].lstrip("/")
    return path


def _to_container(path: Path) -> str:
    """נתיב file:// שהשרת יוכל לפתוח.

    התמונה המראה של _translate. הקובץ שלנו יושב במארח, והשרת רץ
    בקונטיינר שרואה רק את תיקיית הנתונים שחוברה לו — נתיב אחר הוא
    "can't find real file path" מבחינתו.

    לכן הקובץ מונח בתוך התיקייה המשותפת, ועדיף בקישור קשיח: אותה
    מחיצה, ולכן זה מיידי גם לקובץ של ג'יגה־בייטים, ובלי להכפיל מקום.
    כשהקישור אינו אפשרי מעתיקים.
    """
    if not config.BOT_API_DATA:
        return path.resolve().as_uri()
    outbox = Path(config.BOT_API_DATA) / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    staged = outbox / path.name
    if staged.exists():
        staged.unlink()
    try:
        os.link(path, staged)
    except OSError:
        shutil.copy2(path, staged)
    inside = config.BOT_API_INSIDE.rstrip("/")
    return f"file://{inside}/outbox/{staged.name}"


def clear_outbox(name: str) -> None:
    """מסיר את הקישור שהונח לשליחה."""
    if not config.BOT_API_DATA:
        return
    staged = Path(config.BOT_API_DATA) / "outbox" / name
    try:
        staged.unlink(missing_ok=True)
    except OSError as exc:
        log.debug("ניקוי outbox נכשל: %s", exc)


# סיומות וטיפוסי MIME של קובצי כתוביות
SUBTITLE_SUFFIXES = (".srt", ".ass", ".ssa", ".vtt", ".sub", ".sbv")
SUBTITLE_MIMES = ("application/x-subrip", "text/vtt", "text/plain",
                  "application/octet-stream")


def media_of(message: dict) -> tuple[str, int, str]:
    """מחלץ (file_id, גודל, שם) מהודעה, או ריק כשאין מדיה."""
    for key in ("video", "document", "animation"):
        item = message.get(key)
        if item:
            return (item.get("file_id", ""),
                    int(item.get("file_size", 0) or 0),
                    item.get("file_name", "") or f"{key}.mp4")
    return "", 0, ""


def photo_of(message: dict) -> tuple[str, int]:
    """(file_id, גודל) של הגודל הגדול ביותר בתמונה, או ריק.

    טלגרם שולחת תמונה כמערך של גדלים, מהקטן לגדול. media_of מתעלם
    ממנה לגמרי כי היא אינה וידאו ואינה מסמך
    """
    sizes = message.get("photo") or []
    if not sizes:
        # תמונה שנשלחה כקובץ שומרת על האיכות המלאה, ולכן זו דווקא
        # הדרך העדיפה לשלוח אותה — ויש לקלוט גם אותה
        item = message.get("document") or {}
        kind = (item.get("mime_type") or "").lower()
        if kind.startswith("image/"):
            return item.get("file_id", ""), int(item.get("file_size", 0) or 0)
        return "", 0
    largest = max(sizes, key=lambda s: int(s.get("file_size", 0) or 0))
    return largest.get("file_id", ""), int(largest.get("file_size", 0) or 0)


def looks_like_subtitle(message: dict) -> bool:
    """האם ההודעה נושאת קובץ כתוביות.

    השם לבדו אינו אמין: כש-file_name חסר, media_of ממציא "document.mp4"
    וקובץ ה-SRT נראה כמו סרטון חדש — ואז הבוט פתח עבודה שלמה במקום
    להשתמש בכתוביות שנשלחו. כאן נבדקים גם טיפוס ה-MIME וגם העובדה
    שמדובר במסמך ולא בסרטון
    """
    item = message.get("document")
    if not item:
        return False
    name = (item.get("file_name") or "").lower()
    if name.endswith(SUBTITLE_SUFFIXES):
        return True
    mime = (item.get("mime_type") or "").lower()
    # מסמך קטן שאינו וידאו ואינו תמונה הוא כמעט תמיד קובץ כתוביות
    small = int(item.get("file_size", 0) or 0) <= 4 * 1024 * 1024
    return small and (mime in SUBTITLE_MIMES or mime.startswith("text/"))
