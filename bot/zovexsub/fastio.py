"""הורדה והעלאה מהירות מול טלגרם.

שני צווארי בקבוק היו כאן. הראשון הוא ההצפנה: כל בייט שעובר מול טלגרם
מוצפן ב-AES, ובלי החבילה cryptg זה נעשה בפייתון טהור — סדר גודל של
0.4MB לשנייה, לעומת כ-70MB לשנייה בקוד C. די להתקין אותה.

השני הוא הסדרתיות: טלתון מבקש חלק, ממתין לתשובה, מבקש את הבא. על חיבור
עם השהיה זה מבזבז את רוב הזמן בהמתנה. כאן מריצים כמה בקשות במקביל, מה
שממלא את רוחב הפס גם כשכל בקשה בנפרד איטית.

כל מסלול מהיר נופל חזרה למימוש של טלתון אם משהו משתבש.
"""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import math
import logging
import os
from pathlib import Path

from telethon import utils
from telethon.network import MTProtoSender
from telethon.tl import functions, types
from telethon.tl.alltlobjects import LAYER

from . import config

log = logging.getLogger(__name__)

PART = 512 * 1024      # גודל חלק שטלגרם מאפשר להעלאה
MAX_PARTS = 4000       # תקרת החלקים שטלגרם מקבל


def crypto_ready() -> bool:
    """האם ההצפנה רצה בקוד C ולא בפייתון."""
    return importlib.util.find_spec("cryptg") is not None


async def download(client, message, dst: Path, on_progress=None) -> Path:
    """מוריד בכמה בקשות במקביל, עם נפילה חזרה להורדה הרגילה."""
    size = int(getattr(getattr(message, "file", None), "size", 0) or 0)
    workers = _connections(size, max(1, config.TG_CONNECTIONS))

    if size < 8 * 1024 * 1024 or workers == 1:
        await message.download_media(file=str(dst), progress_callback=on_progress)
        return dst

    try:
        return await asyncio.wait_for(
            _parallel_download(client, message, dst, size, workers, on_progress),
            timeout=config.TG_FAST_TIMEOUT or None)
    except (Exception, asyncio.TimeoutError) as exc:  # noqa: BLE001
        log.warning("ההורדה המקבילה נכשלה (%s: %s), עוברים להורדה רגילה",
                    type(exc).__name__, exc)
        await message.download_media(file=str(dst), progress_callback=on_progress)
        return dst


def _parts(size: int) -> int:
    """גודל חלק שטלגרם מקבל, לפי גודל הקובץ.

    טלתון יודע לגזור אותו: 128KB לקובץ קטן, 512KB לקובץ גדול. קודם
    השתמשתי ב-1MB קבוע, וזה חרג ממה שהשרת מוכן לתת — הבקשה הראשונה
    עברה והשאר פשוט לא נענו.
    """
    return utils.get_appropriated_part_size(size) * 1024


def _connections(size: int, ceiling: int) -> int:
    """כמה חיבורים לפתוח. קובץ קטן לא מצדיק עשרים חיבורים."""
    scaled = math.ceil(size / (100 * 1024 * 1024) * ceiling)
    return max(1, min(ceiling, scaled))


async def _open_senders(client, dc_id: int, count: int) -> list:
    """פותח count חיבורים נפרדים ל-DC של טלגרם.

    טלתון מחזיק חיבור אחד לכל DC — קובץ ב-DC הביתי עובר דרך
    self._sender, וקובץ מרוחק דרך חיבור מושאל יחיד שנשמר במטמון לפי
    מספר ה-DC. טלגרם מגביל קצב לכל חיבור בנפרד, ולכן חיבור נפרד לכל
    עובד הוא מה שבאמת מכפיל את הקצב.

    ב-DC הביתי משתמשים באותו מפתח הצפנה ולא שולחים שום בקשת אתחול —
    זה מה שהמימוש המוכר עושה, וזה מה שחסר לי קודם.
    """
    dc = await client._get_dc(dc_id)
    home = client.session.dc_id == dc_id
    senders = []
    try:
        for _ in range(count):
            sender = MTProtoSender(client.session.auth_key if home else None,
                                   loggers=client._log)
            await sender.connect(client._connection(
                dc.ip_address, dc.port, dc.id,
                loggers=client._log, proxy=client._proxy,
            ))
            if not home:
                # DC אחר מחייב ייצוא הרשאה. נעשה סדרתית בכוונה: הראשון
                # מייצא, והשאר כבר מקבלים מפתח מוכן
                auth = await client(functions.auth.ExportAuthorizationRequest(dc_id))
                init = copy.copy(client._init_request)
                init.query = functions.auth.ImportAuthorizationRequest(
                    id=auth.id, bytes=auth.bytes)
                await sender.send(functions.InvokeWithLayerRequest(LAYER, init))
            senders.append(sender)
    except Exception:
        await _close_senders(senders)
        raise
    log.info("נפתחו %d חיבורים נפרדים ל-DC %d%s",
             len(senders), dc_id, "" if home else " (עם ייצוא הרשאה)")
    return senders


async def _close_senders(senders: list) -> None:
    for sender in senders:
        try:
            await sender.disconnect()
        except Exception:  # noqa: BLE001 — סגירה לא אמורה להפיל כלום
            pass


async def _parallel_download(client, message, dst: Path, size: int,
                             workers: int, on_progress) -> Path:
    dc_id, location = utils.get_input_location(message.media)
    dc_id = dc_id or client.session.dc_id

    with dst.open("wb") as fh:
        fh.truncate(size)

    part = _parts(size)
    workers = min(workers, -(-size // part))
    total_parts = -(-size // part)
    stride = workers * part

    done = 0
    lock = asyncio.Lock()
    handle = os.open(dst, os.O_WRONLY)
    senders = await asyncio.wait_for(
        _open_senders(client, dc_id, workers), timeout=config.TG_CONNECT_TIMEOUT)

    async def worker(index: int, sender) -> None:
        """כל חיבור לוקח חלק אחד מכל workers — שזירה ולא טווח רציף."""
        nonlocal done
        offset = index * part
        remaining = len(range(index, total_parts, workers))
        while remaining > 0:
            # _call ולא sender.send: הוא מטפל ב-FloodWait, בשגיאות RPC
            # ובניתוקים. שליחה גולמית פשוט נתקעת כשמשהו משתבש
            result = await client._call(
                sender, functions.upload.GetFileRequest(
                    location, offset=offset, limit=part))
            if isinstance(result, types.upload.FileCdnRedirect):
                raise RuntimeError("טלגרם הפנה ל-CDN, אין תמיכה במסלול המהיר")
            block = bytes(result.bytes)[: max(0, size - offset)]
            if not block:
                break
            os.pwrite(handle, block, offset)
            async with lock:
                done += len(block)
                if on_progress:
                    await on_progress(done, size)
            offset += stride
            remaining -= 1

    try:
        log.info("מוריד ב-%d חיבורים, חלק %dKB, %d חלקים (%.0fMB)",
                 workers, part // 1024, total_parts, size / 1048576)
        await asyncio.gather(*(worker(i, sender)
                               for i, sender in enumerate(senders)))
    finally:
        os.close(handle)
        await _close_senders(senders)

    actual = dst.stat().st_size
    if actual != size:
        raise RuntimeError(f"גודל לא תואם: {actual} במקום {size}")
    return dst


async def upload(client, path: Path, on_progress=None):
    """מעלה בכמה בקשות במקביל ומחזיר קלט מוכן לשליחה, או None לנפילה חזרה."""
    size = path.stat().st_size
    workers = _connections(size, max(1, config.TG_CONNECTIONS))
    parts = -(-size // PART)

    if size < 8 * 1024 * 1024 or workers == 1 or parts > MAX_PARTS:
        return None

    try:
        return await asyncio.wait_for(
            _parallel_upload(client, path, size, parts, workers, on_progress),
            timeout=config.TG_FAST_TIMEOUT or None)
    except (Exception, asyncio.TimeoutError) as exc:  # noqa: BLE001
        log.warning("ההעלאה המקבילה נכשלה (%s: %s), עוברים להעלאה רגילה",
                    type(exc).__name__, exc)
        return None


async def _parallel_upload(client, path: Path, size: int, parts: int,
                           workers: int, on_progress):
    file_id = int.from_bytes(os.urandom(8), "big", signed=True)
    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(parts):
        queue.put_nowait(index)

    done = 0
    lock = asyncio.Lock()
    handle = os.open(path, os.O_RDONLY)
    # אותה בעיה בדיוק כמו בהורדה: client(...) שולח דרך החיבור הראשי
    # היחיד, ולכן כל החלקים הסתדרו בתור על חיבור אחד
    senders = await asyncio.wait_for(
        _open_senders(client, client.session.dc_id, workers),
        timeout=config.TG_CONNECT_TIMEOUT)

    async def worker(sender) -> None:
        nonlocal done
        while True:
            try:
                index = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            block = os.pread(handle, PART, index * PART)
            # _call ולא send גולמי, מאותה סיבה כמו בהורדה
            await client._call(sender, functions.upload.SaveBigFilePartRequest(
                file_id=file_id, file_part=index, file_total_parts=parts, bytes=block,
            ))
            async with lock:
                done += len(block)
                if on_progress:
                    await on_progress(done, size)

    try:
        log.info("מעלה ב-%d חיבורים במקביל (%.0fMB, %d חלקים)",
                 workers, size / 1048576, parts)
        await asyncio.gather(*(worker(sender) for sender in senders))
    finally:
        os.close(handle)
        await _close_senders(senders)

    return types.InputFileBig(id=file_id, parts=parts, name=path.name)


def video_attributes(path: Path, duration: float = 0.0,
                     width: int = 0, height: int = 0) -> list:
    """תכונות וידאו, כדי שההעלאה הידנית תיראה בטלגרם כמו סרטון רגיל."""
    return [types.DocumentAttributeVideo(
        duration=int(duration), w=int(width) or 1280, h=int(height) or 720,
        supports_streaming=True,
    ), types.DocumentAttributeFilename(file_name=path.name)]
