"""userbot בטלגרם: מגיבים לסרטון עם פקודה, ומקבלים SRT בעברית.

רץ על חשבון יוזר רגיל (עם Premium מקבלים קבצים עד 4GB).
עבודה אחת בכל רגע — תור, כדי לא להעמיס את השרת.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename

from . import allowlist, config, pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("zovexsub")

T = config.TRIGGER

HELP = f"""**בוט כתוביות — זובקס**

שולחים סרטון, ואז **מגיבים להודעה של הסרטון** עם:
• `{T}` — קובץ SRT בעברית
• `{T} צריבה` — גם וידאו עם כתוביות צרובות (רק עד {config.BURN_MAX_MINUTES} דקות)

סרטון בלי תגובה עם פקודה — לא קורה כלום.
תמלול עד {config.MAX_INPUT_MINUTES} דקות, כל שפה, הפלט תמיד עברית."""

OWNER_HELP = f"""**פקודות ניהול (רק אתה)**

• `{T} id` בתגובה להודעה — מראה את ה-ID של מי ששלח אותה
• `{T} הוסף` בתגובה להודעה — מאשר את מי ששלח אותה
• `{T} הוסף 123456789` — מאשר לפי ID
• `{T} הסר 123456789` / `{T} הסר` בתגובה — מבטל אישור
• `{T} רשימה` — כל המאושרים
• `{T} עזרה` — ההוראות למשתמשים"""

BURN_WORDS = {"צריבה", "צרוב", "burn", "hardsub", "לצרוב"}


@dataclass
class Job:
    event: events.NewMessage.Event
    message: object
    burn: bool
    status: object


queue: asyncio.Queue[Job] = asyncio.Queue()
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


async def on_command(event: events.NewMessage.Event) -> None:
    text = (event.raw_text or "").strip()
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

    burn = any(word in body for word in BURN_WORDS)
    status = await event.reply("📥 בתור…" if queue.qsize() else "📥 מוריד את הקובץ…")
    await queue.put(Job(event, replied, burn, status))
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


async def worker() -> None:
    while True:
        job = await queue.get()
        work = config.WORK_DIR / uuid.uuid4().hex[:10]
        try:
            await _handle(job, work)
        except Exception as exc:  # noqa: BLE001 — מדווחים לצ'אט ולא מפילים את הבוט
            log.exception("העבודה נכשלה")
            await _safe_edit(job.status, f"❌ {exc}")
        finally:
            pipeline.cleanup(work)
            queue.task_done()


async def _handle(job: Job, work: Path) -> None:
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

    result = await pipeline.run(source, work, burn=job.burn, progress=progress)

    summary = (
        f"✅ **{result.cues} כתוביות** · {result.duration / 60:.1f} דק׳ · "
        f"שפת מקור: `{result.language}` · {result.elapsed / 60:.1f} דק׳ עיבוד"
    )
    if result.burn_skipped:
        summary += f"\n⚠️ {result.burn_skipped}"

    await job.event.reply(summary, file=str(result.srt_path))
    if result.burned_path:
        await _safe_edit(job.status, "📤 מעלה את הוידאו הצרוב…")
        await job.event.reply("🔥 וידאו עם כתוביות צרובות",
                              file=str(result.burned_path), supports_streaming=True)
    await _safe_delete(job.status)


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

    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(config.TG_SESSION, config.TG_API_ID, config.TG_API_HASH)
    client.add_event_handler(
        on_command,
        events.NewMessage(pattern=rf"^\{T}(\s|$)", incoming=True, outgoing=True),
    )
    await client.start()

    global me_id
    me = await client.get_me()
    me_id = me.id
    log.info("מחובר כ-%s (id=%s) · %d מורשים · %d מפתחות Groq · %d מפתחות Gemini",
             me.username or me.first_name, me.id, len(allowlist.listing()),
             len(config.GROQ_API_KEYS), len(config.GEMINI_API_KEYS))
    log.info("טריגר: %s · רשימת מורשים: %s", T, config.ALLOWLIST_FILE)

    asyncio.create_task(worker())
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
