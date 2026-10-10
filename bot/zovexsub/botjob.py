"""מריץ עבודה שהתחילה בבוט, מקצה לקצה.

מסלול נפרד מזה של חשבון המשתמש, בכוונה: הצינור הישן בנוי סביב אירועי
Telethon, והבוט עובד מול שרת HTTP מקומי. במקום לכופף אחד לשני, לכל
אחד נהג משלו — וכך תקלה בחדש אינה נוגעת בישן.

היתרון המרכזי כאן הוא שאין הורדה: השרת המקומי כבר שמר את הסרטון על
הדיסק, ו-getFile מחזיר את נתיבו. אנחנו רק קוראים אותו.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from pathlib import Path

from . import botmenu, config, localbot, media, pipeline

log = logging.getLogger(__name__)

# עבודות שממתינות לקובץ כתוביות מהמשתמש, לפי צ'אט
_waiting: dict[int, Path] = {}


class Screen:
    """הודעה אחת שמתעדכנת, עם ויסות כדי לא להציף את טלגרם."""

    def __init__(self, chat_id, message_id: int):
        self.chat_id = chat_id
        self.message_id = message_id
        self.last = 0.0
        self.shown = ""

    async def show(self, text: str, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self.last < config.BOT_EDIT_EVERY
                          or text == self.shown):
            return
        self.last, self.shown = now, text
        try:
            await localbot.edit(self.chat_id, self.message_id, text)
        except Exception as exc:  # noqa: BLE001 — דיווח לא מפיל עבודה
            log.debug("עדכון מסך נכשל: %s", exc)


async def _fetch(chat_id, file_id: str, name: str, work: Path) -> Path | None:
    """מביא את הסרטון לתיקיית העבודה — בלי הורדה מטלגרם."""
    found, why = await localbot.locate(file_id)
    if found is None:
        # הסיבה נשלחת למשתמש ולא רק ללוג: בלעדיה כל כשל נראה זהה,
        # וההודעה הכללית הקודמת שלחה לחפש בכיוון הלא נכון
        log.warning("קריאת הסרטון נכשלה: %s", why)
        await localbot.say(chat_id, f"לא הצלחתי לקרוא את הסרטון.\n<code>{why}</code>")
        return None
    target = work / f"source{Path(name).suffix or '.mp4'}"
    # העתקה ולא הזזה: הקובץ שייך לשרת, והוא עשוי להידרש לו שוב
    await asyncio.get_running_loop().run_in_executor(
        None, shutil.copy2, found, target)
    log.info("הסרטון נקרא מהדיסק (%.0fMB) — בלי הורדה מטלגרם",
             target.stat().st_size / 1048576)
    return target


async def run(choice) -> None:
    """מריץ עבודה שהתחילה בלחיצה על כפתור."""
    chat_id = choice.chat_id
    work = config.WORK_DIR / uuid.uuid4().hex[:10]
    work.mkdir(parents=True, exist_ok=True)
    note = await localbot.say(chat_id, "📥 קורא את הסרטון…")
    screen = Screen(chat_id, note.get("message_id", 0))

    try:
        source = await _fetch(chat_id, choice.file_id, choice.name, work)
        if source is None:
            pipeline.cleanup(work)
            return

        if choice.source == "own":
            # ממתינים לקובץ הכתוביות; _subtitle_file ימשיך מכאן
            _waiting[int(chat_id)] = source
            await screen.show("📄 שלח עכשיו את קובץ הכתוביות.", force=True)
            return

        async def progress(text: str) -> None:
            await screen.show(text)

        result = await pipeline.run(source, work, progress=progress)
        await screen.show(
            f"✅ <b>{result.cues} כתוביות</b> · {result.duration / 60:.1f} דק׳ · "
            f"שפת מקור: {result.language}", force=True)
        await localbot.call("sendDocument", chat_id=str(chat_id),
                            document=Path(result.srt_path).resolve().as_uri())
        await _offer_burn(chat_id, source, Path(result.srt_path), work)
    except Exception as exc:  # noqa: BLE001 — מדווחים ולא מפילים את הבוט
        log.exception("עבודת הבוט נכשלה")
        await screen.show(f"❌ {exc}", force=True)
        pipeline.cleanup(work)


async def take_subtitle(chat_id, file_id: str, name: str) -> None:
    """קובץ כתוביות שהמשתמש שלח לעבודה שממתינה."""
    source = _waiting.pop(int(chat_id), None)
    if source is None:
        await localbot.say(chat_id, "אין עבודה שממתינה לקובץ. שלח קודם סרטון.")
        return
    found, why = await localbot.locate(file_id)
    if found is None:
        await localbot.say(chat_id,
                           f"לא הצלחתי לקרוא את קובץ הכתוביות.\n<code>{why}</code>")
        return
    work = source.parent
    srt_path = work / "given.srt"
    shutil.copy2(found, srt_path)
    await _offer_burn(chat_id, source, srt_path, work)


async def _offer_burn(chat_id, source: Path, srt_path: Path, work: Path) -> None:
    async def chosen(choice) -> None:
        if choice.cancelled:
            pipeline.cleanup(work)
            return
        await _burn(chat_id, source, srt_path, work, choice)

    await botmenu.offer(chat_id, chosen)


async def _burn(chat_id, source: Path, srt_path: Path, work: Path,
                choice) -> None:
    note = await localbot.say(chat_id, "🔥 צורב…")
    screen = Screen(chat_id, note.get("message_id", 0))
    dst = work / f"{source.stem}.he.mp4"
    try:
        async def on_burn(fraction: float, speed: str) -> None:
            await screen.show(f"🔥 צורב · {fraction * 100:.0f}% · {speed}")

        style = media.Style(size=choice.size, font=choice.font,
                            look=choice.look)
        await media.burn(source, srt_path, dst, on_progress=on_burn,
                         style=style)
        await screen.show("📤 שולח…", force=True)
        info = await media.probe(dst)
        stream = next((s for s in info.get("streams", [])
                       if s.get("codec_type") == "video"), {})
        await localbot.send_video(
            chat_id, dst, caption="🔥 וידאו עם כתוביות צרובות",
            duration=int(float(info.get("format", {}).get("duration", 0) or 0)),
            width=int(stream.get("width", 0) or 0),
            height=int(stream.get("height", 0) or 0),
            thumb=await media.poster(dst, work))
        await screen.show("✅ הסתיים", force=True)
    except Exception as exc:  # noqa: BLE001
        log.exception("הצריבה בבוט נכשלה")
        await screen.show(f"❌ {exc}", force=True)
    finally:
        pipeline.cleanup(work)


def install() -> None:
    """מחבר את הבוט לנהג הזה."""
    botmenu.on_choice = run
    botmenu.on_subtitle = take_subtitle
