"""מריץ עבודה שהתחילה בבוט, מקצה לקצה.

מסלול נפרד מזה של חשבון המשתמש, בכוונה: הצינור הישן בנוי סביב אירועי
Telethon, והבוט עובד מול שרת HTTP מקומי. במקום לכופף אחד לשני, לכל
אחד נהג משלו — וכך תקלה בחדש אינה נוגעת בישן.

את הסרטון מביאים במסלול המקבילי שלנו ולא דרך getFile: שרת ה-Bot API
מוריד בחיבור סדרתי אחד, ועל מכונה שמושכת 80MB/s מהאינטרנט הוא נתן
1.2MB/s. getFile נשאר כגיבוי.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from pathlib import Path

from . import botapi, botmenu, config, fastio, fileid, localbot, media, pipeline

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


def _folder_size(folder: str) -> int:
    """כמה נתונים יש כבר בתיקיית השרת — סימן שההורדה מתקדמת."""
    if not folder:
        return 0
    root = Path(folder)
    if not root.exists():
        return 0
    try:
        return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    except OSError:
        return 0


def _as_document(found: "fileid.Located", size: int, name: str):
    """עוטף את המיקום המפוענח בצורה שהצינור המקבילי כבר יודע לקרוא."""
    from telethon.tl import types

    return types.Document(
        id=found.id, access_hash=found.access_hash,
        file_reference=found.file_reference,
        date=None, mime_type="video/mp4", size=size,
        dc_id=found.dc_id, attributes=[types.DocumentAttributeFilename(name)])


class _Carrier:
    """הודעה מדומה — fastio קורא ממנה רק media וגודל."""

    def __init__(self, document):
        self.media = document
        self.document = document
        self.file = type("F", (), {"size": document.size})()


async def _fast(file_id: str, size: int, name: str, target: Path,
                screen: "Screen") -> bool:
    """מנסה להוריד במסלול המקבילי. מחזיר False כדי ליפול לגיבוי."""
    # הבוט ולא חשבון משתמש. file_id קשור לבוט שקיבל אותו ואינו ניתן
    # להעברה — חשבון אחר שמנסה להשתמש בו מקבל אפס בייטים, וזה בדיוק
    # מה שנמדד. ההנחה שבוט אינו יכול auth.exportAuthorization הייתה
    # שגויה: התיעוד הרשמי מתיר אותה גם לבוטים, והתקיעה שנראתה אז
    # נגרמה מלולאת העדכונים החסומה. כך בנויים בוטי ההזרמה המהירים
    client, which = botapi.bot(), "בוט"
    if client is None or not size:
        return False
    try:
        found = fileid.decode(file_id)
    except ValueError as exc:
        log.info("file_id לא נפענח (%s) — מסלול השרת", exc)
        return False

    began = time.monotonic()
    workers = fastio._connections(size, max(1, config.TG_CONNECTIONS))
    # הערכים שבאמת בתוקף, לא אלה שבקוד: .env גובר על ברירות המחדל,
    # ודריסה ישנה של TG_CONNECTIONS הסתירה שעות של כוונון
    log.info("הורדה מקבילית: %d חיבורים (תקרה %d), %d בקשות לחיבור, "
             "תקרת באוויר %d",
             workers, config.TG_CONNECTIONS, config.TG_PIPELINE,
             config.TG_INFLIGHT_MAX)
    moved = {"at": 0}

    async def on_progress(done: int, total: int, note: str) -> None:
        moved["at"] = done
        elapsed = max(0.1, time.monotonic() - began)
        rate = done / elapsed / 1048576
        await screen.show(
            f"📥 מוריד ·{workers}× · {done * 100 // max(1, total)}% · "
            f"{rate:.1f}MB/s{' · ' + note if note else ''}")

    # דופק: פתיחת שישה־עשר חיבורים נפרדת לוקחת שניות, ועד הבייט
    # הראשון on_progress לא נקרא אף פעם. בלי זה המסך נשאר על ההודעה
    # הראשונה והכל נראה תקוע — וזה בדיוק מה שדווח
    async def beat() -> None:
        while True:
            await asyncio.sleep(config.BOT_EDIT_EVERY)
            if moved["at"]:
                continue
            waited = int(time.monotonic() - began)
            if waited > config.FAST_START_TIMEOUT:
                # אף בייט לא הגיע. עדיף ליפול לגיבוי מאשר להישאר תקוע
                raise TimeoutError(
                    f"לא התחיל להוריד תוך {config.FAST_START_TIMEOUT:.0f} שניות")
            await screen.show(f"🔌 פותח {workers} חיבורים ({which}) · "
                              f"{waited // 60}:{waited % 60:02d}")

    # קוראים ל-_parallel_download ישירות ולא ל-download: האחרון בולע כשל
    # מקבילי ועובר בשקט למסלול סדרתי, וזה בדיוק מה שהסתיר קצב של
    # 1.2MB/s שנראה כאילו המקבול עובד. כאן כשל הוא כשל, והוא נאמר
    carrier = _Carrier(_as_document(found, size, name))
    pulse = asyncio.create_task(beat())
    puller = asyncio.ensure_future(fastio._parallel_download(
        client, carrier, target, size, workers, on_progress))
    try:
        done, _ = await asyncio.wait([puller, pulse],
                                     return_when=asyncio.FIRST_COMPLETED)
        if pulse in done:          # הדופק נפל על פסק זמן — אין התחלה
            puller.cancel()
            raise pulse.exception() or TimeoutError("ההורדה לא התחילה")
        await puller
    except Exception as exc:  # noqa: BLE001 — נופלים לגיבוי, לא מפילים
        log.warning("המסלול המקבילי נכשל (%s: %s) — מסלול השרת",
                    type(exc).__name__, exc)
        await screen.show(f"⚠️ המסלול המהיר נפל: {type(exc).__name__}: {exc}",
                          force=True)
        target.unlink(missing_ok=True)
        return False
    finally:
        pulse.cancel()
        puller.cancel()
    if target.stat().st_size < size:
        target.unlink(missing_ok=True)
        return False
    log.info("ירד במסלול המקבילי: %.0fMB ב-%.0f שניות",
             size / 1048576, time.monotonic() - began)
    return True


async def _fetch(chat_id, file_id: str, name: str, work: Path,
                 screen: "Screen", size: int = 0) -> Path | None:
    """מביא את הסרטון לתיקיית העבודה."""
    target = work / f"source{Path(name).suffix or '.mp4'}"
    if await _fast(file_id, size, name, target, screen):
        return target
    # getFile במצב --local מוריד את הקובץ מטלגרם לפני שהוא מחזיר נתיב.
    # זו הורדה אמיתית שלוקחת זמן, ובלי דופק המסך נראה תקוע — בדיוק
    # אותה תקלה שתוקנה כבר בשאר הצינור
    async def beat() -> None:
        began = time.monotonic()
        # מדידת גידול ולא גודל מוחלט: התיקייה מחזיקה גם הורדות קודמות,
        # ולכן המונה הראה 1555MB לקובץ של 949MB. ההפרש הוא מה שירד עכשיו
        before = _folder_size(config.BOT_API_DATA)
        while True:
            await asyncio.sleep(config.BOT_EDIT_EVERY)
            waited = int(time.monotonic() - began)
            grown = max(0, _folder_size(config.BOT_API_DATA) - before)
            extra = f" · {grown / 1048576:.0f}MB" if grown else ""
            await screen.show(f"📥 השרת מוריד את הסרטון · "
                              f"{waited // 60}:{waited % 60:02d}{extra}")

    pulse = asyncio.create_task(beat())
    try:
        found, why = await localbot.locate(file_id)
    finally:
        pulse.cancel()
    if found is None:
        # הסיבה נשלחת למשתמש ולא רק ללוג: בלעדיה כל כשל נראה זהה,
        # וההודעה הכללית הקודמת שלחה לחפש בכיוון הלא נכון
        log.warning("קריאת הסרטון נכשלה: %s", why)
        await localbot.say(chat_id, f"לא הצלחתי לקרוא את הסרטון.\n<code>{why}</code>")
        return None
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
        source = await _fetch(chat_id, choice.file_id, choice.name,
                              work, screen, choice.size_bytes)
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
        srt_file = Path(result.srt_path)
        try:
            await localbot.call("sendDocument", chat_id=str(chat_id),
                                document=localbot._to_container(srt_file))
        finally:
            localbot.clear_outbox(srt_file.name)
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
        # "מהיר" פורץ את הסולם האוטומטי, שהוא HEVC בלבד: H.264 מקודד
        # מהר בהרבה ומנגן בכל מקום, במחיר קובץ גדול יותר
        profile = {"מהיר": "fast", "איכותי": "balanced"}.get(choice.speed, "")
        await media.burn(source, srt_path, dst, on_progress=on_burn,
                         style=style, profile=profile)
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


def waiting_for(chat_id) -> bool:
    """האם העבודה בצ'אט הזה ממתינה לקובץ כתוביות מהמשתמש."""
    return int(chat_id) in _waiting


def install() -> None:
    """מחבר את הבוט לנהג הזה."""
    botmenu.on_choice = run
    botmenu.on_subtitle = take_subtitle
    botmenu.on_waiting = waiting_for
