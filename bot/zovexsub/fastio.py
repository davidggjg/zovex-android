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
import importlib.util
import logging
import os
from pathlib import Path

from telethon.tl import functions, types

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
    workers = max(1, config.TG_CONNECTIONS)

    if size < 8 * 1024 * 1024 or workers == 1:
        await message.download_media(file=str(dst), progress_callback=on_progress)
        return dst

    try:
        return await _parallel_download(client, message, dst, size, workers, on_progress)
    except Exception as exc:  # noqa: BLE001 — נפילה חזרה עדיפה על כישלון
        log.warning("ההורדה המקבילה נכשלה (%s), עוברים להורדה רגילה", exc)
        await message.download_media(file=str(dst), progress_callback=on_progress)
        return dst


async def _parallel_download(client, message, dst: Path, size: int,
                             workers: int, on_progress) -> Path:
    with dst.open("wb") as fh:
        fh.truncate(size)

    chunk = 1024 * 1024
    span = max(chunk, -(-size // workers) // chunk * chunk)
    done = 0
    lock = asyncio.Lock()
    handle = os.open(dst, os.O_WRONLY)

    async def worker(start: int) -> None:
        nonlocal done
        end = min(start + span, size)
        if start >= end:
            return
        position = start
        async for block in client.iter_download(
            message, offset=start, request_size=chunk,
            limit=-(-(end - start) // chunk),
        ):
            block = bytes(block)[: end - position]
            if not block:
                break
            os.pwrite(handle, block, position)
            position += len(block)
            async with lock:
                done += len(block)
                if on_progress:
                    await on_progress(done, size)
            if position >= end:
                break

    try:
        log.info("מוריד ב-%d בקשות במקביל (%.0fMB)", workers, size / 1048576)
        await asyncio.gather(*(worker(i * span) for i in range(workers)))
    finally:
        os.close(handle)

    actual = dst.stat().st_size
    if actual != size:
        raise RuntimeError(f"גודל לא תואם: {actual} במקום {size}")
    return dst


async def upload(client, path: Path, on_progress=None):
    """מעלה בכמה בקשות במקביל ומחזיר קלט מוכן לשליחה, או None לנפילה חזרה."""
    size = path.stat().st_size
    workers = max(1, config.TG_CONNECTIONS)
    parts = -(-size // PART)

    if size < 8 * 1024 * 1024 or workers == 1 or parts > MAX_PARTS:
        return None

    try:
        return await _parallel_upload(client, path, size, parts, workers, on_progress)
    except Exception as exc:  # noqa: BLE001
        log.warning("ההעלאה המקבילה נכשלה (%s), עוברים להעלאה רגילה", exc)
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

    async def worker() -> None:
        nonlocal done
        while True:
            try:
                index = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            block = os.pread(handle, PART, index * PART)
            await client(functions.upload.SaveBigFilePartRequest(
                file_id=file_id, file_part=index, file_total_parts=parts, bytes=block,
            ))
            async with lock:
                done += len(block)
                if on_progress:
                    await on_progress(done, size)

    try:
        log.info("מעלה ב-%d בקשות במקביל (%.0fMB, %d חלקים)",
                 workers, size / 1048576, parts)
        await asyncio.gather(*(worker() for _ in range(workers)))
    finally:
        os.close(handle)

    return types.InputFileBig(id=file_id, parts=parts, name=path.name)


def video_attributes(path: Path, duration: float = 0.0,
                     width: int = 0, height: int = 0) -> list:
    """תכונות וידאו, כדי שההעלאה הידנית תיראה בטלגרם כמו סרטון רגיל."""
    return [types.DocumentAttributeVideo(
        duration=int(duration), w=int(width) or 1280, h=int(height) or 720,
        supports_streaming=True,
    ), types.DocumentAttributeFilename(file_name=path.name)]
