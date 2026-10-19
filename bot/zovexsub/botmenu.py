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

from . import config, fetch, localbot

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
    source_message: int = 0      # ההודעה שבה הגיע הסרטון, להעברה לאחסון
    size_bytes: int = 0
    name: str = ""
    source: str = ""             # make / own
    cover: str = ""              # תמונת תצוגה מקדימה: כן / לא
    speed: str = ""              # מהיר (H.264) / איכותי (H.265)
    url: str = ""                # קישור, כשהעבודה התחילה מקישור
    quality: str = ""            # רזולוציית ההורדה מקישור


# כל שלב: כותרת, שורות כפתורים, והשדה שנשמר
# כל שלב: כותרת, שורות כפתורים, השדה שנשמר, ואם הוא חל רק על קישור.
# בחירת רזולוציה חסרת משמעות לקובץ שכבר נשלח — הגודל שלו נקבע
STEPS = (
    ("📏 <b>גודל הכתוביות</b>",
     [[("קטן (מומלץ)", "size:קטן"), ("בינוני", "size:בינוני")],
      [("גדול", "size:גדול")]],
     "size", False),
    ("🔤 <b>גופן</b>",
     [[("DejaVu Sans", "font:dejavu"), ("FreeSans", "font:free")],
      [("ברירת מחדל", "font:ברירת מחדל")]],
     "font", False),
    ("🎨 <b>מראה</b>",
     [[("⬛ רקע שחור", "look:קופסה")],
      [("⬜ לבן בלבד", "look:לבן")],
      [("✒️ לבן עם קו מתאר", "look:קו")]],
     "look", False),
    ("🖼️ <b>תמונת תצוגה מקדימה?</b>\n\n"
     "התמונה שתשלח תהיה מה שרואים לפני שפותחים את הסרטון.\n"
     "<i>טלגרם מקטינה כל תצוגה מקדימה ל-320 פיקסל — זו מגבלה שלה.</i>",
     [[("🖼️ כן, אשלח תמונה", "cover:כן")],
      [("🎞️ לא, פריים מהסרטון", "cover:לא")]],
     "cover", False),
    ("⚙️ <b>איכות הצריבה</b>\n\n"
     "<b>איכותית</b> — H.265, קובץ קטן יותר באותה איכות.\n"
     "<b>מהירה</b> — H.264, מסיימת מהר יותר, קובץ גדול יותר.",
     [[("💎 איכותית (מומלץ)", "speed:איכותי")],
      [("⚡ מהירה", "speed:מהיר")]],
     "speed", False),
)

QUALITY = ("🎞️ <b>באיזו איכות להוריד?</b>\n\n"
           "ככל שגבוה יותר — הורדה ארוכה יותר וצריבה ארוכה יותר.")
# רשימת גיבוי בלבד, כשבדיקת הקישור נכשלת. הרשימה האמיתית נבנית
# מהרזולוציות שקיימות בקישור עצמו
QUALITY_KEYS = [
    [("1080p", "q:1080"), ("720p", "q:720")],
    [("480p", "q:480"), ("360p", "q:360")],
    [("🔝 הטובה ביותר", "q:best")],
    [("❌ ביטול", "cancel")],
]


def quality_keys(tall: list[int]) -> list:
    """בונה את כפתורי האיכות מהרזולוציות שבאמת קיימות בקישור.

    רשימה קבועה היא הבטחה שאי אפשר לעמוד בה: לסרטון אחד יש 1080p
    ולאחר רק 360p. כאן מוצג בדיוק מה שיש, שניים בשורה
    """
    if not tall:
        return QUALITY_KEYS
    buttons = [(f"{h}p", f"q:{h}") for h in tall]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([("🔝 הטובה ביותר", "q:best")])
    rows.append([("❌ ביטול", "cancel")])
    return rows

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
on_waiting = None
# on_cover כשהמשתמש שלח תמונה לתצוגה מקדימה, on_wanting_cover כדי
# לדעת אם מחכים לאחת
on_cover = None
on_wanting_cover = None


def _applies(index: int, choice: "Choice") -> bool:
    """האם השלב הזה רלוונטי לעבודה הנוכחית."""
    return not STEPS[index][3] or bool(choice.url)


def _steps_for(choice: "Choice") -> list[int]:
    """רשימת השלבים שיוצגו בפועל, לפי סוג העבודה."""
    return [i for i in range(len(STEPS)) if _applies(i, choice)]


def _advance(choice: "Choice") -> int:
    """השלב הבא שרלוונטי, או len(STEPS) כשנגמרו."""
    index = choice.step + 1
    while index < len(STEPS) and not _applies(index, choice):
        index += 1
    return index


def _menu(index: int, choice: "Choice") -> tuple[str, str]:
    title, rows, _, _ = STEPS[index]
    shown = _steps_for(choice)
    text = f"{title}  <i>({shown.index(index) + 1}/{len(shown)})</i>"
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


async def greet(chat_id, file_id: str, size: int, name: str,
                source_message: int = 0) -> None:
    """שואל מה לעשות עם סרטון שהתקבל, לפני שמתחיל עיבוד."""
    sent = await localbot.say(chat_id, SOURCE,
                              buttons=localbot.keyboard(SOURCE_KEYS))
    message_id = sent.get("message_id")
    if not message_id:
        return
    choice = Choice(chat_id=int(chat_id), message_id=message_id)
    choice.file_id, choice.size_bytes, choice.name = file_id, size, name
    choice.source_message = source_message
    _open[message_id] = choice
    log.info("סרטון התקבל בבוט: %s (%.0fMB)", name, size / 1048576)


async def greet_link(chat_id, url: str) -> None:
    """מתחיל עבודה מקישור, באותו מסלול כפתורים כמו סרטון שנשלח.

    קודם קישור לא עשה כלום: _incoming בדק רק מדיה, וטקסט קיבל את
    ההודעה "שלח סרטון ואתחיל" — גם כשהיה בו קישור תקין שההורדה
    יודעת להוריד
    """
    # הודעת ביניים: בדיקת הקישור לוקחת שניות, ובלעדיה נראה שלא קרה כלום
    sent = await localbot.say(chat_id, "🔎 בודק אילו איכויות זמינות…")
    message_id = sent.get("message_id")
    if not message_id:
        return
    choice = Choice(chat_id=int(chat_id), message_id=message_id)
    choice.url, choice.name = url, "link.mp4"
    _open[message_id] = choice
    log.info("קישור התקבל בבוט: %s", url[:120])

    tall = await fetch.heights(url)
    title = QUALITY
    if not tall:
        title += "\n\n<i>לא הצלחתי לקרוא את האיכויות מהקישור — " \
                 "הרשימה כללית.</i>"
    await localbot.edit(chat_id, message_id, title,
                        buttons=localbot.keyboard(quality_keys(tall)))


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

    if data.startswith("q:"):
        choice.quality = data.split(":", 1)[1]
        await localbot.edit(choice.chat_id, message_id, SOURCE,
                            buttons=localbot.keyboard(SOURCE_KEYS))
        return

    if data.startswith("src:"):
        choice.source = data.split(":", 1)[1]
        label = ("מייצר כתוביות…" if choice.source == "make"
                 else "שלח עכשיו את קובץ הכתוביות (SRT).")
        await localbot.edit(choice.chat_id, message_id, f"✅ {label}")
        _open.pop(message_id, None)
        if on_choice:
            _detach(on_choice(choice), "עבודה מהבוט")
        return

    if data == "burn:yes":
        choice.step = next(iter(_steps_for(choice)), len(STEPS))
        text, keys = _menu(choice.step, choice)
        await localbot.edit(choice.chat_id, message_id, text, buttons=keys)
        return

    if ":" not in data:
        return
    field_name, value = data.split(":", 1)
    expected = STEPS[choice.step][2] if choice.step < len(STEPS) else ""
    if field_name != expected:
        return                      # לחיצה על כפתור של שלב קודם
    setattr(choice, field_name, value)
    choice.step = _advance(choice)

    if choice.step < len(STEPS):
        text, keys = _menu(choice.step, choice)
        await localbot.edit(choice.chat_id, message_id, text, buttons=keys)
        return

    _open.pop(message_id, None)
    picked = " · ".join(x for x in (choice.quality, choice.size, choice.look,
                                    choice.speed) if x)
    await localbot.edit(choice.chat_id, message_id, f"✅ נבחר: {picked}")
    if choice.done:
        _detach(choice.done(choice), "עבודה מהבוט")


# משימות רקע חיות. בלי החזקת הפניה אוסף הזבל של asyncio עלול לאסוף
# משימה באמצע ריצה, והעבודה פשוט נעלמת
_running: set = set()


def _detach(coro, label: str) -> None:
    """מריץ עבודה ארוכה ברקע כדי שלולאת העדכונים תישאר פנויה.

    זה היה הבאג: _pump קרא לעבודה ב-await ישיר, ולכן מרגע הלחיצה על
    הכפתור האחרון הבוט הפסיק להגיב לכל הודעה — הורדה, תרגום וצריבה
    החזיקו את הלולאה היחידה. מהמשתמש זה נראה כמו בוט מת.
    """
    task = asyncio.ensure_future(coro)
    _running.add(task)

    def finished(done) -> None:
        _running.discard(done)
        if not done.cancelled() and done.exception():
            log.error("%s נכשל: %s", label, done.exception())

    task.add_done_callback(finished)


async def _incoming(message: dict) -> None:
    """הודעה שנכנסה לבוט.

    בוט ייעודי אינו צריך פקודות: סרטון שנשלח אליו מתחיל את התהליך,
    וכל השאר קורה בכפתורים. קובץ כתוביות נשלח כשהמשתמש בחר לצרוב
    קובץ משלו, ומטופל על ידי מי שמחזיק את העבודה הפתוחה.
    """
    chat = (message.get("chat") or {}).get("id")
    if not chat:
        return
    # תמונה לתצוגה מקדימה קודמת לכל זיהוי אחר: היא מגיעה כ-photo,
    # ש-media_of מתעלם ממנו לגמרי, ואז ההודעה הייתה נופלת לענף
    # "שלח סרטון או קישור" כאילו לא הבנו אותה
    if on_wanting_cover and on_wanting_cover(chat):
        shot, _ = localbot.photo_of(message)
        if shot:
            if on_cover:
                _detach(on_cover(chat, shot), "תמונת תצוגה מקדימה")
            return

    file_id, size, name = localbot.media_of(message)
    if not file_id:
        text = (message.get("text") or "").strip()
        if not text:
            return
        link = fetch.find_url(text)
        if link:
            await greet_link(chat, link)
            return
        await localbot.say(chat, "שלח סרטון או קישור ואתחיל. "
                                 "אין צורך בפקודות.")
        return
    # עבודה שממתינה לכתוביות גוברת על כל זיהוי: אם המשתמש ביקש לצרוב
    # קובץ משלו ושלח מסמך, זה הקובץ — גם כשהשם חסר או מטעה
    expected = bool(on_waiting and on_waiting(chat) and message.get("document"))
    if expected or localbot.looks_like_subtitle(message):
        if on_subtitle:
            _detach(on_subtitle(chat, file_id, name), "קובץ כתוביות")
        else:
            await localbot.say(chat, "קיבלתי קובץ כתוביות אבל אין לי מה לעשות "
                                     "איתו. שלח קודם סרטון.")
        return
    await greet(chat, file_id, size, name, message.get("message_id") or 0)


async def _pump() -> None:
    """מושך עדכונים מהבוט ומטפל בלחיצות."""
    offset = 0
    misses = 0
    while True:
        try:
            batch = await localbot.updates(offset)
        except asyncio.CancelledError:
            raise
        except Exception as exc:    # noqa: BLE001 — רשת נופלת, ממשיכים
            # רמת debug הסתירה את התקלה הגרועה מכולן: כששרת ה-Bot API
            # המקומי אינו עולה, כל משיכה נכשלת והבוט חירש לנצח — בלי
            # קריסה, בלי שגיאה בלוג, ובלי שום סימן חיצוני
            misses += 1
            if misses in (3, 20) or misses % 100 == 0:
                log.error("משיכת עדכונים נכשלה %d פעמים ברציפות (%s) — "
                          "האם שרת ה-Bot API המקומי רץ על %s?",
                          misses, exc, config.BOT_API_URL)
            else:
                log.debug("משיכת עדכונים נכשלה: %s", exc)
            await asyncio.sleep(5)
            continue
        if misses:
            log.info("משיכת העדכונים חזרה אחרי %d כשלונות", misses)
            misses = 0
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


async def _supervise() -> None:
    """מחזיק את לולאת העדכונים חיה.

    _pump יוצא רק על חריגה שאינה מהרשת, ואז הבוט חי אבל חירש לנצח —
    אין קריסה, אין restart של systemd, ואין שום סימן חיצוני. כאן כל
    יציאה נרשמת והלולאה קמה מחדש.
    """
    while True:
        try:
            await _pump()
        except asyncio.CancelledError:
            raise
        except Exception:           # noqa: BLE001 — חירשות גרועה מקריסה
            log.exception("לולאת העדכונים נפלה — מרימים מחדש")
        else:
            log.error("לולאת העדכונים יצאה בלי שגיאה — מרימים מחדש")
        await asyncio.sleep(5)


def start() -> None:
    """מפעיל את ההאזנה ללחיצות, אם יש בוט."""
    global _loop
    if _loop is not None:
        log.info("לולאת הכפתורים כבר רצה")
        return
    # שתיקה כאן הייתה בלתי ניתנת לאבחון: בלי טוקן או בלי כתובת שרת
    # הבוט פשוט לא הקשיב, ושום שורה בלוג לא אמרה למה
    if not localbot.available():
        log.error("ממשק הכפתורים כבוי: BOT_TOKEN=%s, BOT_API_URL=%s",
                  "יש" if config.BOT_TOKEN else "חסר",
                  config.BOT_API_URL or "חסר")
        return
    _loop = asyncio.create_task(_supervise())
    log.info("מאזין ללחיצות כפתורים בבוט · %s", config.BOT_API_URL)


def stop() -> None:
    global _loop
    if _loop is not None:
        _loop.cancel()
        _loop = None
