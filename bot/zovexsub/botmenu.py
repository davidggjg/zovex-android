"""תפריט כפתורים בבוט, במקום "השב בתגובה".

בוט ייעודי לא צריך פקודות: המשתמש שולח סרטון, ומכאן הכל בלחיצות.
כל שאלה עורכת את אותה הודעה לשאלה הבאה, כך שהצ'אט לא מתמלא.

הלחיצות מגיעות כ-callback_query, ולכן צריך מישהו שימשוך עדכונים.
הלולאה כאן עושה זאת עם timeout בצד השרת — חיבור אחד פתוח במקום
סיבובים מיותרים.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from . import localbot

log = logging.getLogger(__name__)

# הצעות פתוחות לפי מזהה ההודעה שנערכת
_open: dict[int, "Choice"] = {}
_loop: asyncio.Task | None = None


@dataclass
class Choice:
    """בחירה שמתגלגלת משאלה לשאלה."""
    chat_id: int
    message_id: int = 0
    step: int = 0
    size: str = ""
    font: str = ""
    look: str = ""
    done: object = None          # נקרא עם Choice כשהמשתמש סיים
    cancelled: bool = False
    file_id: str = ""            # הסרטון שהתקבל, כשהשיחה התחילה ממנו
    size_bytes: int = 0
    name: str = ""
    source: str = ""             # make / own


# כל שלב: כותרת, שורות כפתורים, והשדה שנשמר
STEPS = (
    ("📏 <b>גודל הכתוביות</b>",
     [[("קטן", "size:קטן"), ("בינוני", "size:בינוני"), ("גדול", "size:גדול")]],
     "size"),
    ("🔤 <b>גופן</b>",
     [[("DejaVu Sans", "font:dejavu"), ("FreeSans", "font:free")],
      [("ברירת מחדל", "font:ברירת מחדל")]],
     "font"),
    ("🎨 <b>מראה</b>",
     [[("⬛ רקע שחור", "look:קופסה")],
      [("⬜ לבן בלבד", "look:לבן")],
      [("✒️ לבן עם קו מתאר", "look:קו")]],
     "look"),
)

ASK = ("❓ <b>לצרוב את הכתוביות על הסרטון?</b>\n\n"
       "הכתוביות כבר נשלחו למעלה.")
ASK_KEYS = [[("✅ כן", "burn:yes"), ("❌ לא", "burn:no")]]

# השאלה הראשונה, מיד אחרי שהסרטון מתקבל ולפני שמתחיל עיבוד כלשהו
SOURCE = "🎬 <b>הסרטון התקבל</b>\n\nמה לעשות עם הכתוביות?"
SOURCE_KEYS = [[("🤖 תייצר לי כתוביות", "src:make")],
               [("📄 יש לי קובץ כתוביות", "src:own")],
               [("❌ ביטול", "cancel")]]

# נקראים מבחוץ. on_choice כשהמשתמש בחר מה לעשות עם סרטון,
# on_subtitle כששלח קובץ כתוביות משלו
on_choice = None
on_subtitle = None


def _menu(index: int) -> tuple[str, str]:
    title, rows, _ = STEPS[index]
    text = f"{title}  <i>({index + 1}/{len(STEPS)})</i>"
    return text, localbot.keyboard(rows + [[("❌ ביטול", "cancel")]])


async def offer(chat_id, on_done) -> None:
    """שולח את שאלת הצריבה עם כפתורים."""
    sent = await localbot.say(chat_id, ASK,
                              buttons=localbot.keyboard(ASK_KEYS))
    message_id = sent.get("message_id")
    if not message_id:
        raise RuntimeError("ההצעה נשלחה בלי מזהה הודעה")
    _open[message_id] = Choice(chat_id=int(chat_id), message_id=message_id,
                               done=on_done)
    log.info("הצעת צריבה עם כפתורים (הודעה %s)", message_id)


async def greet(chat_id, file_id: str, size: int, name: str) -> None:
    """שואל מה לעשות עם סרטון שהתקבל, לפני שמתחיל עיבוד."""
    sent = await localbot.say(chat_id, SOURCE,
                              buttons=localbot.keyboard(SOURCE_KEYS))
    message_id = sent.get("message_id")
    if not message_id:
        return
    choice = Choice(chat_id=int(chat_id), message_id=message_id)
    choice.file_id, choice.size_bytes, choice.name = file_id, size, name
    _open[message_id] = choice
    log.info("סרטון התקבל בבוט: %s (%.0fMB)", name, size / 1048576)


async def _press(query: dict) -> None:
    """מטפל בלחיצה אחת."""
    data = query.get("data") or ""
    message = query.get("message") or {}
    message_id = message.get("message_id")
    choice = _open.get(message_id)
    await localbot.tap(query.get("id", ""))
    if choice is None:
        return

    if data == "cancel" or data == "burn:no":
        _open.pop(message_id, None)
        choice.cancelled = True
        await localbot.edit(choice.chat_id, message_id,
                            "בוטל. הכתוביות נשלחו למעלה.")
        return

    if data.startswith("src:"):
        choice.source = data.split(":", 1)[1]
        label = ("מייצר כתוביות…" if choice.source == "make"
                 else "שלח עכשיו את קובץ הכתוביות (SRT).")
        await localbot.edit(choice.chat_id, message_id, f"✅ {label}")
        _open.pop(message_id, None)
        if on_choice:
            await on_choice(choice)
        return

    if data == "burn:yes":
        choice.step = 0
        text, keys = _menu(0)
        await localbot.edit(choice.chat_id, message_id, text, buttons=keys)
        return

    if ":" not in data:
        return
    field_name, value = data.split(":", 1)
    expected = STEPS[choice.step][2] if choice.step < len(STEPS) else ""
    if field_name != expected:
        return                      # לחיצה על כפתור של שלב קודם
    setattr(choice, field_name, value)
    choice.step += 1

    if choice.step < len(STEPS):
        text, keys = _menu(choice.step)
        await localbot.edit(choice.chat_id, message_id, text, buttons=keys)
        return

    _open.pop(message_id, None)
    picked = " · ".join(x for x in (choice.size, choice.look) if x)
    await localbot.edit(choice.chat_id, message_id, f"✅ נבחר: {picked}")
    if choice.done:
        await choice.done(choice)


async def _incoming(message: dict) -> None:
    """הודעה שנכנסה לבוט.

    בוט ייעודי אינו צריך פקודות: סרטון שנשלח אליו מתחיל את התהליך,
    וכל השאר קורה בכפתורים. קובץ כתוביות נשלח כשהמשתמש בחר לצרוב
    קובץ משלו, ומטופל על ידי מי שמחזיק את העבודה הפתוחה.
    """
    chat = (message.get("chat") or {}).get("id")
    if not chat:
        return
    file_id, size, name = localbot.media_of(message)
    if not file_id:
        text = (message.get("text") or "").strip()
        if text:
            await localbot.say(chat, "שלח סרטון ואתחיל. אין צורך בפקודות.")
        return
    if name.lower().endswith((".srt", ".ass", ".vtt", ".sub")):
        if on_subtitle:
            await on_subtitle(chat, file_id, name)
        return
    await greet(chat, file_id, size, name)


async def _pump() -> None:
    """מושך עדכונים מהבוט ומטפל בלחיצות."""
    offset = 0
    while True:
        try:
            batch = await localbot.updates(offset)
        except asyncio.CancelledError:
            raise
        except Exception as exc:    # noqa: BLE001 — רשת נופלת, ממשיכים
            log.debug("משיכת עדכונים נכשלה: %s", exc)
            await asyncio.sleep(5)
            continue
        for update in batch:
            offset = max(offset, int(update.get("update_id", 0)) + 1)
            try:
                query = update.get("callback_query")
                if query:
                    await _press(query)
                    continue
                message = update.get("message")
                if message:
                    await _incoming(message)
            except Exception as exc:  # noqa: BLE001 — עדכון אחד לא מפיל
                log.exception("טיפול בעדכון נכשל: %s", exc)


def start() -> None:
    """מפעיל את ההאזנה ללחיצות, אם יש בוט."""
    global _loop
    if _loop is not None or not localbot.available():
        return
    _loop = asyncio.create_task(_pump())
    log.info("מאזין ללחיצות כפתורים בבוט")


def stop() -> None:
    global _loop
    if _loop is not None:
        _loop.cancel()
        _loop = None
