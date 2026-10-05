"""userbot בטלגרם: מגיבים לסרטון עם פקודה, ומקבלים SRT בעברית.

רץ על חשבון יוזר רגיל (עם Premium מקבלים קבצים עד 4GB).
עבודה אחת בכל רגע — תור, כדי לא להעמיס את השרת.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename

from . import allowlist, config, diagnose, fastio, fetch, media, pipeline, progress as prog

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

אפשר גם קישור: `{T} https://...` — אני אוריד את הווידאו בעצמי.

כשהכתוביות מוכנות אני שולח את קובץ ה-SRT. אם הסרטון קצר
מ-{config.BURN_MAX_MINUTES} דקות, אציע לצרוב אותן על הסרטון —
עונים `כן` בתגובה להצעה, ורק אז הצריבה מתחילה.

**יש לך כבר קובץ כתוביות?** הגב לסרטון עם `{T} צריבה`,
אני אבקש את הקובץ, ואצרוב אותו בלי לתמלל מחדש.

תמלול עד {config.MAX_INPUT_MINUTES} דקות, כל שפה, הפלט תמיד עברית."""

OWNER_HELP = f"""**פקודות ניהול (רק אתה)**

• `{T} id` בתגובה להודעה — מראה את ה-ID של מי ששלח אותה
• `{T} הוסף` בתגובה להודעה — מאשר את מי ששלח אותה
• `{T} הוסף 123456789` — מאשר לפי ID
• `{T} הסר 123456789` / `{T} הסר` בתגובה — מבטל אישור
• `{T} רשימה` — כל המאושרים
• `{T} בדיקה` בתגובה לסרטון — דוח תזמונים לאבחון סנכרון
• `{T} עצור` — **עוצר מיד כל מה שרץ**, מרוקן את התור ומוחק את כל הקבצים
• `{T} עזרה` — ההוראות למשתמשים"""

# רק צורות שמתחילות בנקודה. מילה רגילה כמו "כתוביות" או "srt" מופיעה
# בשיחות רגילות, ובוט שמגיב לה מתפרץ לשיחות שלא קשורות אליו.
ALIASES = {T, ".כתוביות", ".תמלל"}

# סיומות וידאו, לזיהוי קובץ המקור בתיקיית העבודה
VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v",
                  ".ts", ".mpg", ".mpeg", ".wmv", ".flv", ".3gp", ".ogv"}

YES_WORDS = {"כן", "כן!", "yes", "y", "לצרוב", "צרוב", "צריבה", "כן בבקשה", "✅", "👍"}
OFFER_TTL = 1800  # חצי שעה לענות להצעת הצריבה, ואז הקבצים נמחקים


@dataclass
class Job:
    event: events.NewMessage.Event
    message: object           # ההודעה שמכילה את הסרטון (או None כשיש קישור)
    status: object            # הודעת ההתקדמות
    srt_path: Path | None = None   # אם מוגדר — זו עבודת צריבה בלבד
    work: Path | None = None
    diagnose: bool = False    # מפיק דוח תזמונים במקום כתוביות
    url: str = ""             # אם מוגדר — מורידים מהקישור במקום מטלגרם
    srt_message: object = None  # קובץ כתוביות שהמשתמש שלח, לצריבה ישירה


@dataclass
class Pending:
    """בקשת צריבה שממתינה לקובץ הכתוביות של המשתמש."""
    video: object
    message: object
    user_id: int
    expires: float


@dataclass
class Offer:
    """הצעת צריבה שממתינה ל"כן" של המשתמש."""
    work: Path
    source: Path
    srt_path: Path
    message: object
    user_id: int
    expires: float


# שני תורים נפרדים: צריבה של שעתיים לא תחסום בקשת כתוביות של דקה
queue: asyncio.Queue[Job] = asyncio.Queue()
burn_queue: asyncio.Queue[Job] = asyncio.Queue()
burning = 0          # כמה צריבות רצות ברגע זה
offers: dict[int, Offer] = {}      # לפי מזהה הודעת ההצעה
waiting: dict[int, Pending] = {}   # בקשות שממתינות לקובץ כתוביות
running: dict[int, asyncio.Task] = {}   # עבודות שרצות ברגע זה, לביטול
me_id: int = 0


async def _run_job(handler, job: "Job", work: Path) -> None:
    """מריץ עבודה כמשימה נפרדת, כדי שאפשר יהיה לבטל אותה בלי להפיל את העובד.

    current_task כאן היה המשימה של העובד עצמו, לא של העבודה. ביטול היה
    הורג את העובד — וגרוע מזה, העובד תפס את הביטול והמשיך ללולאה, כך
    שה-gather שממתין לו בעצירה לא היה נגמר לעולם.
    """
    task = asyncio.create_task(handler(job, work))
    running[id(task)] = task
    try:
        await task
    finally:
        running.pop(id(task), None)


def _drain(q: asyncio.Queue) -> int:
    """מרוקן תור ומחזיר כמה עבודות הושלכו."""
    dropped = 0
    while True:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            return dropped
        q.task_done()
        dropped += 1


async def stop_everything() -> tuple[int, int, float]:
    """עוצר כל מה שרץ, מרוקן את התורים ומוחק את כל הקבצים הזמניים."""
    dropped = _drain(queue) + _drain(burn_queue)

    tasks = list(running.values())
    for task in tasks:
        task.cancel()
    if tasks:
        # ffmpeg נהרג מתוך הביטול עצמו, אבל ממתינים שבאמת יסתיים
        await asyncio.gather(*tasks, return_exceptions=True)
    running.clear()
    offers.clear()
    waiting.clear()

    freed = 0.0
    try:
        for item in config.WORK_DIR.iterdir():
            freed += sum(f.stat().st_size for f in item.rglob("*") if f.is_file()) \
                if item.is_dir() else item.stat().st_size
            pipeline.cleanup(item) if item.is_dir() else item.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("ניקוי תיקיית העבודה נכשל: %s", exc)

    log.warning("עצירה מלאה: %d עבודות רצות, %d בתור, %.1fGB שוחררו",
                len(tasks), dropped, freed / 1024 ** 3)
    return len(tasks), dropped, freed / 1024 ** 3


def free_gigabytes() -> float:
    try:
        return shutil.disk_usage(config.WORK_DIR).free / 1024 ** 3
    except OSError:
        return 0.0


def ensure_space(needed_bytes: int) -> None:
    """צריבה צורכת מקום פי כמה מהמקור. עדיף לסרב מראש מאשר למלא דיסק."""
    needed = needed_bytes / 1024 ** 3 * config.DISK_FACTOR + config.DISK_RESERVE_GB
    free = free_gigabytes()
    if free < needed:
        raise RuntimeError(
            f"אין מספיק מקום בדיסק: פנויים {free:.1f}GB, נדרשים {needed:.1f}GB."
        )


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
    head = text.split(maxsplit=1)[0].lower() if text else ""
    try:
        if head in ALIASES:
            await on_command(event, text[len(head):].strip())
        elif event.is_reply:
            await on_subtitle_file(event)
            await on_yes(event, text)
    except Exception:  # noqa: BLE001 — האנדלר לעולם לא מפיל את הבוט
        log.exception("שגיאה בטיפול בהודעה")


async def on_command(event: events.NewMessage.Event, body: str) -> None:
    sender = _who(event.message)
    is_owner = sender == me_id
    replied = await event.get_reply_message()

    # ---- פקודות ניהול ----
    if is_owner:
        if body in ("עצור", "stop", "עצירה"):
            note = await event.reply("🛑 עוצר הכל…")
            stopped, dropped, freed = await stop_everything()
            await _safe_edit(note, (
                "🛑 **נעצר הכל**\n"
                f"• {stopped} עבודות שרצו — בוטלו\n"
                f"• {dropped} עבודות בתור — הושלכו\n"
                f"• {freed:.1f}GB קבצים זמניים — נמחקו\n"
                f"• {free_gigabytes():.0f}GB פנויים בדיסק\n\n"
                "הבוט ממשיך לרוץ ומוכן לעבודה חדשה."
            ))
            return
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

    # אפשר קישור בפקודה עצמה, או תגובה להודעה עם סרטון או עם קישור
    url = fetch.find_url(body) or (fetch.find_url(getattr(replied, "raw_text", "")) if replied else None)
    has_media = bool(replied and replied.media)
    if not url and not has_media:
        await event.reply(
            f"צריך **להגיב** עם `{T}` להודעה שמכילה סרטון, "
            f"או לשלוח `{T} <קישור>`."
        )
        return
    if url and not fetch.available():
        await event.reply("yt-dlp לא מותקן על השרת. התקנה:\n`pip install yt-dlp`")
        return

    # צריבה עם קובץ כתוביות שהמשתמש כבר הכין
    if body.startswith(("צריבה", "צרוב", "לצרוב", "burn", "hardsub")):
        if not has_media:
            await event.reply(f"צריך להגיב עם `{T} צריבה` להודעה שמכילה את הסרטון.")
            return
        if _is_subtitle(event.message):
            await queue_burn(event, replied, event.message)
            return
        prompt = await event.reply(
            "📄 **שלח לי עכשיו את קובץ הכתוביות** (`.srt`) **בתגובה להודעה הזו**, "
            "ואני אצרוב אותו על הסרטון."
        )
        waiting[prompt.id] = Pending(video=replied, message=prompt, user_id=sender,
                                     expires=time.monotonic() + OFFER_TTL)
        log.info("ממתין לקובץ כתוביות (הודעה %s)", prompt.id)
        return

    wants_report = body.startswith(("בדיקה", "אבחון", "debug", "diag"))
    first = "📥 בתור…" if queue.qsize() else (
        "🔗 מוריד מהקישור…" if url else "📥 מוריד את הקובץ…")
    status = await event.reply(first)
    await queue.put(Job(event, replied if has_media else None, status,
                        diagnose=wants_report, url=url or ""))
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


def _is_subtitle(message) -> bool:
    name = _filename(message) if getattr(message, "media", None) else ""
    return name.lower().endswith((".srt", ".vtt", ".ass", ".ssa"))


async def queue_burn(event, video, srt_message) -> None:
    status = await event.reply("🔥 בתור לצריבה…" if _queued() else "📥 מוריד…")
    await burn_queue.put(Job(event, video, status, srt_message=srt_message))
    log.info("צריבה ידנית נוספה לתור")


async def on_subtitle_file(event: events.NewMessage.Event) -> None:
    """קובץ כתוביות שנשלח בתגובה לבקשה — מתחיל צריבה."""
    if not event.is_reply:
        return
    pending = waiting.get(event.reply_to_msg_id)
    if pending is None:
        return
    sender = _who(event.message)
    if sender != pending.user_id and sender != me_id:
        return
    if not _is_subtitle(event.message):
        await event.reply("זה לא נראה כמו קובץ כתוביות. שלח קובץ `.srt`.")
        return

    waiting.pop(event.reply_to_msg_id, None)
    await _safe_delete(pending.message)
    await queue_burn(event, pending.video, event.message)


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
    status = await event.reply("🔥 בתור לצריבה…" if _queued() else "🔥 צורב…")
    await burn_queue.put(Job(event, offer.message, status,
                             srt_path=offer.srt_path, work=offer.work))
    log.info("אושרה צריבה על ידי %s", sender)


async def worker() -> None:
    """מטפל בבקשות כתוביות — קצרות יחסית, לא נחסמות על ידי צריבה."""
    while True:
        job = await queue.get()
        work = config.WORK_DIR / uuid.uuid4().hex[:10]
        try:
            await _run_job(_subtitle, job, work)
        except asyncio.CancelledError:
            log.warning("עבודת הכתוביות בוטלה")
            await _safe_edit(job.status, "🛑 בוטל")
        except Exception as exc:  # noqa: BLE001 — מדווחים לצ'אט ולא מפילים את הבוט
            log.exception("עבודת הכתוביות נכשלה")
            await _safe_edit(job.status, f"❌ {exc}")
        finally:
            # התיקייה נשמרת רק אם נותרה הצעת צריבה פתוחה עליה
            if not any(o.work == work for o in offers.values()):
                pipeline.cleanup(work)
            queue.task_done()


def _queued() -> bool:
    """האם העבודה תמתין — או כי יש תור, או כי כל הצריבות תפוסות."""
    return bool(burn_queue.qsize()) or burning >= max(1, config.BURN_JOBS)


async def burn_worker() -> None:
    """תור נפרד לצריבה, שיכולה לרוץ שעות על קובץ ארוך."""
    while True:
        job = await burn_queue.get()
        work = job.work or config.WORK_DIR / uuid.uuid4().hex[:10]
        global burning
        burning += 1
        try:
            await _run_job(_burn, job, work)
        except asyncio.CancelledError:
            log.warning("הצריבה בוטלה")
            await _safe_edit(job.status, "🛑 בוטל")
        except Exception as exc:  # noqa: BLE001
            log.exception("הצריבה נכשלה")
            await _safe_edit(job.status, f"❌ {exc}")
        finally:
            burning -= 1
            pipeline.cleanup(work)
            burn_queue.task_done()


async def _subtitle(job: Job, work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)

    async def edit(text: str) -> None:
        await _safe_edit(job.status, text)

    if job.url:
        ensure_space(0)
        download = prog.Stage(edit, "🔗 מוריד מהקישור")

        async def on_fetch(done: float, total: float) -> None:
            download.total_bytes = int(total)
            await download.show(done / total if total else 0, done_bytes=int(done))

        source = await fetch.download(job.url, work, on_progress=on_fetch)
        await download.finish()
    else:
        name = _filename(job.message)
        source = work / f"source{Path(name).suffix or '.mp4'}"
        total_bytes = int(getattr(getattr(job.message, "file", None), "size", 0) or 0)
        ensure_space(total_bytes)
        download = prog.Stage(edit, "📥 מוריד", total_bytes=total_bytes)

        async def on_download(received: int, total: int) -> None:
            await download.show(received / total if total else 0, done_bytes=received)

        await fastio.download(job.event.client, job.message, source,
                              on_progress=on_download)
        await download.finish()
    log.info("מקור מוכן: %s (%.1f MB)", source.name, source.stat().st_size / 1048576)

    progress = edit

    if job.diagnose:
        await progress("🔬 מפיק דוח תזמונים…")
        report = await diagnose.report(source, work)
        await job.event.reply("🔬 דוח אבחון תזמונים", file=str(report))
        await _safe_delete(job.status)
        return

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
    async def edit(text: str) -> None:
        await _safe_edit(job.status, text)

    if job.srt_message is not None:
        # צריבה של כתוביות שהמשתמש הביא: צריך להוריד גם את הסרטון וגם אותן
        work.mkdir(parents=True, exist_ok=True)
        total_bytes = int(getattr(getattr(job.message, "file", None), "size", 0) or 0)
        ensure_space(total_bytes)

        download = prog.Stage(edit, "📥 מוריד", total_bytes=total_bytes)

        async def on_download(received: int, total: int) -> None:
            await download.show(received / total if total else 0, done_bytes=received)

        name = _filename(job.message)
        source = work / f"source{Path(name).suffix or '.mp4'}"
        await fastio.download(job.event.client, job.message, source,
                              on_progress=on_download)
        await download.finish()

        job.srt_path = work / "subs.srt"
        await job.srt_message.download_media(file=str(job.srt_path))
        log.info("התקבל קובץ כתוביות: %.0fKB", job.srt_path.stat().st_size / 1024)
    else:
        # בתיקייה יושבים גם source.he.srt ו-source.he.rtl.srt, ולכן אסור
        # לקחת סתם את הראשון לפי שם: מיון אלפביתי מחזיר דווקא כתובית,
        # ואז קריאת אורך הווידאו נכשלת. רק סיומות של וידאו נחשבות.
        source = next((item for item in sorted(work.glob("source.*"))
                       if item.suffix.lower() in VIDEO_SUFFIXES), None)
        if source is None:
            raise FileNotFoundError(
                "קובץ המקור נמחק מהשרת. שלח את הסרטון מחדש.")

    ensure_space(source.stat().st_size)

    stage = prog.Stage(edit, "🔥 צורב")
    stage.pulse()

    async def on_burn(fraction: float, speed: str) -> None:
        # ירידה גדולה פירושה שהצריבה התחילה מחדש (נפילה מהמסלול המקביל
        # לתהליך יחיד), ואז הפס חייב להתאפס. בלי זה המונוטוניות הקפיאה
        # אותו על האחוז הגבוה שהניסיון הקודם הספיק להגיע אליו
        restarted = fraction + 0.05 < stage.fraction
        await stage.show(fraction, note=f"קצב {speed}" if speed else "",
                         force=restarted)

    try:
        burned = await pipeline.burn(source, job.srt_path, work, on_progress=on_burn)
    finally:
        stage.stop()
    await stage.finish()

    upload = prog.Stage(edit, "📤 מעלה", total_bytes=burned.stat().st_size)

    async def on_upload(sent: int, total: int) -> None:
        await upload.show(sent / total if total else 0, done_bytes=sent)

    client = job.event.client
    chat = await job.event.get_input_chat()
    sent_file = await fastio.upload(client, burned, on_progress=on_upload)

    if sent_file is not None:
        info = await media.probe(burned)
        stream = next((s for s in info.get("streams", [])
                       if s.get("codec_type") == "video"), {})
        await client.send_file(
            chat, sent_file, caption="🔥 וידאו עם כתוביות צרובות",
            supports_streaming=True, reply_to=job.event.message.id,
            attributes=fastio.video_attributes(
                burned, float(info.get("format", {}).get("duration", 0) or 0),
                int(stream.get("width", 0) or 0), int(stream.get("height", 0) or 0),
            ),
        )
    else:
        await client.send_file(
            chat, str(burned), caption="🔥 וידאו עם כתוביות צרובות",
            supports_streaming=True, reply_to=job.event.message.id,
            progress_callback=on_upload,
        )
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
        # waiting נבנה עם expires אבל אף אחד לא קרא אותו, אז בקשה שלא
        # קיבלה את קובץ הכתוביות נשארה שם לנצח — והבקשה הישנה נשארה
        # צריבה אפשרית ללא הגבלת זמן
        for message_id, pending in list(waiting.items()):
            if pending.expires <= now:
                waiting.pop(message_id, None)
                log.info("בקשת כתוביות %s פגה בלי קובץ", message_id)


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
    if not fastio.crypto_ready():
        log.warning("cryptg לא מותקן — ההורדה וההעלאה יהיו איטיות פי עשרות! "
                    "התקנה: pip install cryptg")
    log.info("מחובר כ-%s (id=%s) · %d מורשים · %d מפתחות Groq · %d מפתחות Gemini",
             me.username or me.first_name, me.id, len(allowlist.listing()),
             len(config.GROQ_API_KEYS), len(config.GEMINI_API_KEYS))
    log.info("טריגר: %s · רשימת מורשים: %s · תיקיית עבודה: %s",
             T, config.ALLOWLIST_FILE, config.WORK_DIR)

    asyncio.create_task(worker())
    for _ in range(max(1, config.BURN_JOBS)):
        asyncio.create_task(burn_worker())
    asyncio.create_task(expire_offers())
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
