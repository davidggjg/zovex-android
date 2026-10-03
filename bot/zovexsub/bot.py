"""userbot בטלגרם: שולחים סרטון, מקבלים SRT בעברית (ואופציונלית וידאו צרוב).

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

from . import config, pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("zovexsub")

HELP = f"""**בוט כתוביות — זובקס**

שולחים סרטון או קובץ אודיו עם כיתוב:
• `{config.TRIGGER}` — קובץ SRT בעברית
• `{config.TRIGGER} צריבה` — גם וידאו עם כתוביות צרובות (עד {config.BURN_MAX_MINUTES} דקות)

אפשר גם להשיב `{config.TRIGGER}` להודעה עם סרטון.
תמלול עד {config.MAX_INPUT_MINUTES} דקות, כל שפה — הפלט תמיד עברית."""

BURN_WORDS = {"צריבה", "צרוב", "burn", "hardsub", "לצרוב"}


@dataclass
class Job:
    event: events.NewMessage.Event
    message: object
    burn: bool
    status: object


queue: asyncio.Queue[Job] = asyncio.Queue()
me_id: int | None = None


def _authorized(sender_id: int, username: str | None) -> bool:
    if not config.ALLOWED_USERS:
        return sender_id == me_id
    allowed = {u.lower() for u in config.ALLOWED_USERS}
    return str(sender_id) in allowed or (username or "").lower() in allowed


def _filename(message) -> str:
    for attr in getattr(getattr(message, "document", None), "attributes", []) or []:
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    return "video.mp4"


async def on_trigger(event: events.NewMessage.Event) -> None:
    sender = await event.get_sender()
    if not _authorized(event.sender_id, getattr(sender, "username", None)):
        return

    text = (event.raw_text or "")
    if text.strip() in (f"{config.TRIGGER} עזרה", f"{config.TRIGGER} help"):
        await event.reply(HELP)
        return

    media_message = event.message
    if not media_message.media:
        replied = await event.get_reply_message()
        if replied and replied.media:
            media_message = replied
        else:
            await event.reply(
                f"צריך לשלוח סרטון עם הכיתוב `{config.TRIGGER}`, "
                f"או להשיב `{config.TRIGGER}` להודעה עם סרטון."
            )
            return

    burn = any(word in text for word in BURN_WORDS)
    status = await event.reply("📥 בתור…" if queue.qsize() else "📥 מוריד את הקובץ…")
    await queue.put(Job(event, media_message, burn, status))
    log.info("עבודה נוספה לתור (בתור: %d)", queue.qsize())


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
        on_trigger, events.NewMessage(pattern=rf"^\{config.TRIGGER}")
    )
    await client.start()
    global me_id
    me = await client.get_me()
    me_id = me.id
    log.info("מחובר כ-%s (id=%s) · %d מפתחות Groq · %d מפתחות Gemini",
             me.username or me.first_name, me.id,
             len(config.GROQ_API_KEYS), len(config.GEMINI_API_KEYS))
    log.info("טריגר: %s", config.TRIGGER)

    asyncio.create_task(worker())
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
