"""userbot בטלגרם: מגיבים לסרטון עם פקודה, ומקבלים SRT בעברית.

רץ על חשבון יוזר רגיל (עם Premium מקבלים קבצים עד 4GB).
עבודה אחת בכל רגע — תור, כדי לא להעמיס את השרת.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename

from . import allowlist, config, pipeline

LEVEL = getattr(logging, (os.getenv("LOG_LEVEL") or "INFO").upper(), logging.INFO)
logging.basicConfig(level=LEVEL, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
# Telethon ב-DEBUG מציף את הלוג; משאירים רק את שלנו מפורט
logging.getLogger("telethon").setLevel(max(LEVEL, logging.INFO))
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("zovexsub")
log.setLevel(LEVEL)

T = config.TRIGGER

HELP = f"""**בוט כתוביות — זובקס**

שולחים סרטון, ואז **מגיבים להודעה של הסרטון** עם `{T}`.
סרטון בלי תגובה עם הפקודה — לא קורה כלום.

כשהכתוביות מוכנות אני שולח את קובץ ה-SRT. אם הסרטון קצר
מ-{config.BURN_MAX_MINUTES} דקות, אציע לצרוב אותן על הסרטון —
עונים `כן` בתגובה להצעה, ורק אז הצריבה מתחילה.

תמלול עד {config.MAX_INPUT_MINUTES} דקות, כל שפה, הפלט תמיד עברית."""

OWNER_HELP = f"""**פקודות ניהול (רק אתה)**

• `{T} id` בתגובה להודעה — מראה את ה-ID של מי ששלח אותה
• `{T} הוסף` בתגובה להודעה — מאשר את מי ששלח אותה
• `{T} הוסף 123456789` — מאשר לפי ID
• `{T} הסר 123456789` / `{T} הסר` בתגובה — מבטל אישור
• `{T} רשימה` — כל המאושרים
• `{T} עזרה` — ההוראות למשתמשים"""

YES_WORDS = {"כן", "כן!", "yes", "y", "לצרוב", "צרוב", "צריבה", "כן בבקשה", "✅", "👍"}
OFFER_TTL = 1800  # חצי שעה לענות להצעת הצריבה, ואז הקבצים נמחקים


@dataclass
class Job:
    event: events.NewMessage.Event
    message: object           # ההודעה שמכילה את הסרטון
    status: object            # הודעת ההתקדמות
    srt_path: Path | None = None   # אם מוגדר — זו עבודת צריבה בלבד
    work: Path | None = None


@dataclass
class Offer:
    """הצעת צריבה שממתינה ל"כן" של המשתמש."""
    work: Path
    source: Path
    srt_path: Path
    message: object
    user_id: int
    expires: float


queue: asyncio.Queue[Job] = asyncio.Queue()
offers: dict[int, Offer] = {}      # לפי מזהה הודעת ההצעה
me_id: int = 0


def _who(message) -> int:
    """מזהה המשתמש ששלח הודעה (גם בערוצים/קבוצות)."""
    return int(getattr(message, "sender_id", 0) or 0)


def _filename(message) -> str:
    for attr in getattr(getattr(message, "document", None), "attributes", []) or []:
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    return "video.mp4"


def _arg_id(text: str, replied) -> int | None:
    """מוציא ID מהפקודה עצמה, ואם אין — מההודעה שהגיבו אליה."""
    for token in text.split():
        if token.isdigit():
            return int(token)
    return _who(replied) if replied else None


# סימני כיווניות שמקלדת עברית/אנדרואיד מוסיפה בלי שרואים אותם
INVISIBLE = "\u200e\u200f\u202a\u202b\u202c\u2066\u2067\u2068\u2069\ufeff"


def clean(text: str) -> str:
    return (text or "").translate({ord(ch): None for ch in INVISIBLE}).strip()


async def on_message(event: events.NewMessage.Event) -> None:
    """נקודת כניסה יחידה — מנתב לפי התוכן, כדי שלא יהיה סינון סמוי שמפספס."""
    text = clean(event.raw_text)
    log.debug("הודעה מ-%s בצ'אט %s: %r (תגובה: %s)",
              _who(event.message), event.chat_id, text[:60], event.reply_to_msg_id)
    try:
        if text == T or text.startswith(T + " "):
            await on_command(event, text)
        elif event.is_reply:
            await on_yes(event, text)
    except Exception:  # noqa: BLE001 — האנדלר לעולם לא מפיל את הבוט
        log.exception("שגיאה בטיפול בהודעה")


async def on_command(event: events.NewMessage.Event, text: str) -> None:
    body = text[len(T):].strip()
    sender = _who(event.message)
    is_owner = sender == me_id
    replied = await event.get_reply_message()

    # ---- פקודות ניהול ----
    if is_owner:
        if body in ("ניהול", "admin"):
            await event.reply(OWNER_HELP)
            return
        if body.startswith(("id", "איידי", "מזהה")):
            if not replied:
                await event.reply(f"צריך להגיב להודעה של מישהו עם `{T} id`.")
                return
            target = _who(replied)
            name = await _describe(event.client, target)
            mark = "✅ מאושר" if allowlist.is_allowed(target) else "🚫 לא מאושר"
            await event.reply(f"👤 {name}\n`{target}`\n{mark}\n\nלאישור: `{T} הוסף {target}`")
            return
        if body.startswith(("הוסף", "אשר", "allow", "add")):
            target = _arg_id(body, replied)
            if not target:
                await event.reply(f"שימוש: `{T} הוסף 123456789` או `{T} הוסף` בתגובה להודעה.")
                return
            name = await _describe(event.client, target)
            added = allowlist.add(target, name)
            await event.reply(
                f"{'✅ אושר' if added else 'ℹ️ כבר היה מאושר'}: {name} — `{target}`"
            )
            return
        if body.startswith(("הסר", "בטל", "deny", "remove", "block")):
            target = _arg_id(body, replied)
            if not target:
                await event.reply(f"שימוש: `{T} הסר 123456789` או `{T} הסר` בתגובה להודעה.")
                return
            removed = allowlist.remove(target)
            await event.reply(
                f"{'🗑 הוסר' if removed else 'ℹ️ לא היה ברשימה'}: `{target}`"
            )
            return
        if body.startswith(("רשימה", "users", "list")):
            users = allowlist.listing()
            if not users:
                await event.reply("הרשימה ריקה — רק אתה יכול להפעיל.")
                return
            rows = "\n".join(f"• `{uid}` {label}".rstrip() for uid, label in users)
            await event.reply(f"**{len(users)} מאושרים:**\n{rows}")
            return

    if body in ("עזרה", "help"):
        if is_owner or allowlist.is_allowed(sender):
            await event.reply(HELP + ("\n\n" + OWNER_HELP if is_owner else ""))
        return

    # ---- בקשת תמלול ----
    if not (is_owner or allowlist.is_allowed(sender)):
        log.info("נדחה: משתמש לא מאושר %s", sender)
        return

    # חובה להגיב להודעה שמכילה את הסרטון — סרטון לבד לא מפעיל כלום
    if not replied or not replied.media:
        await event.reply(
            f"צריך **להגיב** עם `{T}` להודעה שמכילה את הסרטון."
        )
        return

    status = await event.reply("📥 בתור…" if queue.qsize() else "📥 מוריד את הקובץ…")
    await queue.put(Job(event, replied, status))
    log.info("עבודה נוספה לתור ממשתמש %s (בתור: %d)", sender, queue.qsize())


async def _describe(client: TelegramClient, user_id: int) -> str:
    try:
        entity = await client.get_entity(user_id)
    except Exception:  # noqa: BLE001 — אין גישה לישות, לא נורא
        return ""
    name = " ".join(filter(None, [getattr(entity, "first_name", ""),
                                  getattr(entity, "last_name", "")])).strip()
    username = getattr(entity, "username", "")
    return f"{name} (@{username})" if username else name


async def on_yes(event: events.NewMessage.Event, text: str) -> None:
    """תשובה "כן" בתגובה להצעת הצריבה — רק אז מתחילים לצרוב."""
    offer = offers.get(event.reply_to_msg_id)
    if offer is None:
        return
    if text.strip(".!") not in YES_WORDS:
        return
    sender = _who(event.message)
    if sender != offer.user_id and sender != me_id:
        return

    offers.pop(event.reply_to_msg_id, None)
    status = await event.reply("🔥 בתור לצריבה…" if queue.qsize() else "🔥 צורב…")
    await queue.put(Job(event, offer.message, status,
                        srt_path=offer.srt_path, work=offer.work))
    log.info("אושרה צריבה על ידי %s", sender)


async def worker() -> None:
    while True:
        job = await queue.get()
        burn_job = job.srt_path is not None
        work = job.work if burn_job else config.WORK_DIR / uuid.uuid4().hex[:10]
        try:
            if burn_job:
                await _burn(job, work)
            else:
                await _subtitle(job, work)
        except Exception as exc:  # noqa: BLE001 — מדווחים לצ'אט ולא מפילים את הבוט
            log.exception("העבודה נכשלה")
            await _safe_edit(job.status, f"❌ {exc}")
            if burn_job:
                pipeline.cleanup(work)
        finally:
            # בעבודת תמלול התיקייה נשמרת רק אם יש הצעת צריבה פתוחה
            if not burn_job and not any(o.work == work for o in offers.values()):
                pipeline.cleanup(work)
            queue.task_done()


async def _subtitle(job: Job, work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    name = _filename(job.message)
    source = work / f"source{Path(name).suffix or '.mp4'}"

    last = 0.0

    async def on_download(received: int, total: int) -> None:
        nonlocal last
        if time.monotonic() - last < 6 or not total:
            return
        last = time.monotonic()
        await _safe_edit(job.status, f"📥 מוריד… {received * 100 // total}%")

    await job.message.download_media(file=str(source), progress_callback=on_download)
    log.info("הורד: %s (%.1f MB)", source.name, source.stat().st_size / 1048576)

    async def progress(text: str) -> None:
        await _safe_edit(job.status, text)

    result = await pipeline.run(source, work, progress=progress)

    await job.event.reply(
        f"✅ **{result.cues} כתוביות** · {result.duration / 60:.1f} דק׳ · "
        f"שפת מקור: `{result.language}` · {result.elapsed / 60:.1f} דק׳ עיבוד",
        file=str(result.srt_path),
    )
    await _safe_delete(job.status)

    if result.burnable:
        offer_message = await job.event.reply(
            "רוצה שאצרוב את הכתוביות על הסרטון?\n"
            "**תשלח `כן` בתגובה להודעה הזו.**"
        )
        offers[offer_message.id] = Offer(
            work=work, source=source, srt_path=result.srt_path,
            message=job.message, user_id=_who(job.event.message),
            expires=time.monotonic() + OFFER_TTL,
        )
        log.info("הצעת צריבה פתוחה (הודעה %s)", offer_message.id)
    else:
        await job.event.reply(
            f"ℹ️ הסרטון באורך {result.duration / 60:.0f} דקות, "
            f"וצריבה מתבצעת רק עד {config.BURN_MAX_MINUTES} דקות."
        )


async def _burn(job: Job, work: Path) -> None:
    source = next(work.glob("source.*"))
    burned = await pipeline.burn(source, job.srt_path, work)
    await _safe_edit(job.status, "📤 מעלה את הוידאו הצרוב…")
    await job.event.reply("🔥 וידאו עם כתוביות צרובות",
                          file=str(burned), supports_streaming=True)
    await _safe_delete(job.status)
    pipeline.cleanup(work)


async def expire_offers() -> None:
    """מנקה הצעות צריבה שלא נענו, ואיתן את הקבצים הזמניים."""
    while True:
        await asyncio.sleep(120)
        now = time.monotonic()
        for message_id, offer in list(offers.items()):
            if offer.expires <= now:
                offers.pop(message_id, None)
                pipeline.cleanup(offer.work)
                log.info("הצעת צריבה %s פגה, הקבצים נמחקו", message_id)


async def _safe_edit(status, text: str) -> None:
    try:
        await status.edit(text)
    except Exception:  # noqa: BLE001 — עריכה זהה/מהירה מדי זורקת, לא מעניין
        pass


async def _safe_delete(status) -> None:
    try:
        await status.delete()
    except Exception:  # noqa: BLE001
        pass


async def main() -> None:
    problems = config.validate()
    if problems:
        raise SystemExit("שגיאות הגדרה ב-.env:\n- " + "\n- ".join(problems))

    # ניקוי שאריות מהרצה קודמת — לא משאירים סרטונים על השרת
    pipeline.cleanup(config.WORK_DIR)
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(config.TG_SESSION, config.TG_API_ID, config.TG_API_HASH)
    client.add_event_handler(on_message, events.NewMessage())
    await client.start()

    global me_id
    me = await client.get_me()
    me_id = me.id
    log.info("מחובר כ-%s (id=%s) · %d מורשים · %d מפתחות Groq · %d מפתחות Gemini",
             me.username or me.first_name, me.id, len(allowlist.listing()),
             len(config.GROQ_API_KEYS), len(config.GEMINI_API_KEYS))
    log.info("טריגר: %s · רשימת מורשים: %s · תיקיית עבודה: %s",
             T, config.ALLOWLIST_FILE, config.WORK_DIR)

    asyncio.create_task(worker())
    asyncio.create_task(expire_offers())
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
