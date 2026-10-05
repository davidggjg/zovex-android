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
import time
import logging
import os
from pathlib import Path

from telethon import utils
from telethon.network import MTProtoSender
from telethon.errors import FloodWaitError
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
    """מוריד, וממשיך מאיפה שנעצר אם ההורדה נקטעה.

    הלקח מהלילה הזה: קוד העברה שכתבתי בעצמי נשבר שוב ושוב, בעוד
    download_media של הספרייה פשוט עובד. לכן המסלול הרגיל הוא של טלתון,
    והמסלול המקבילי שלי נכנס רק אם ביקשו אותו במפורש.

    והחידוש האמיתי: הורדה שנקטעה ב-82% כבר לא מתחילה מאפס. הבייטים
    שעל הדיסק נשמרים, והניסיון הבא ממשיך בדיוק משם.
    """
    size = int(getattr(getattr(message, "file", None), "size", 0) or 0)
    workers = _connections(size, max(1, config.TG_CONNECTIONS))

    if size and workers > 1 and size >= 8 * 1024 * 1024:
        try:
            return await asyncio.wait_for(
                _parallel_download(client, message, dst, size, workers, on_progress),
                timeout=config.TG_FAST_TIMEOUT or None)
        except (Exception, asyncio.TimeoutError) as exc:  # noqa: BLE001
            log.warning("ההורדה המקבילה נכשלה (%s: %s), עוברים למסלול הרגיל",
                        type(exc).__name__, exc)
            dst.unlink(missing_ok=True)

    last = 0
    for attempt in range(1, config.TG_READ_RETRIES + 1):
        have = dst.stat().st_size if dst.exists() else 0
        if size and have >= size:
            return dst
        if have and have == last:
            log.warning("הניסיון לא התקדם מעבר ל-%.0fMB", have / 1048576)
        last = have
        try:
            await _resume_download(client, message, dst, size, have, on_progress)
            if not size or dst.stat().st_size >= size:
                return dst
            log.warning("ההורדה נקטעה על %.0f%% — ממשיכים מאותה נקודה",
                        dst.stat().st_size * 100 / size)
        except Exception as exc:  # noqa: BLE001
            got = dst.stat().st_size if dst.exists() else 0
            log.warning("ההורדה נכשלה ב-%.0fMB (%s: %s), ניסיון %d/%d",
                        got / 1048576, type(exc).__name__, exc,
                        attempt, config.TG_READ_RETRIES)
            if attempt == config.TG_READ_RETRIES:
                raise
        await asyncio.sleep(min(10, 2 ** attempt))

    return dst


async def _resume_download(client, message, dst: Path, size: int, have: int,
                           on_progress) -> None:
    """מוריד מהנקודה שבה נעצרנו, עם זיהוי תקיעה.

    iter_download עם offset הוא מה שמאפשר את ההמשכיות — download_media
    תמיד מתחיל מאפס, ולכן הפסקה ב-82% הייתה מוחקת שעה של הורדה.
    """
    if have:
        log.info("ממשיך הורדה מ-%.0fMB מתוך %.0fMB",
                 have / 1048576, size / 1048576)
    done = have
    stalled = time.monotonic()

    async def guard() -> None:
        while True:
            await asyncio.sleep(10)
            if time.monotonic() - stalled > config.TG_STALL_TIMEOUT:
                raise TimeoutError(
                    f"לא ירד אף בייט {config.TG_STALL_TIMEOUT:.0f} שניות")

    async def pull() -> None:
        nonlocal done, stalled
        with dst.open("ab" if have else "wb") as fh:
            async for block in client.iter_download(message, offset=have):
                fh.write(block)
                done += len(block)
                stalled = time.monotonic()
                if on_progress:
                    await on_progress(done, size or done)

    watch = asyncio.create_task(guard())
    try:
        puller = asyncio.ensure_future(pull())
        finished, _ = await asyncio.wait([puller, watch],
                                         return_when=asyncio.FIRST_COMPLETED)
        if watch in finished:
            puller.cancel()
            raise watch.exception() or TimeoutError("ההורדה תקועה")
        await puller
    finally:
        watch.cancel()


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
    key = client.session.auth_key if home else None
    senders = []
    try:
        for _ in range(count):
            sender = MTProtoSender(key, loggers=client._log)
            await sender.connect(client._connection(
                dc.ip_address, dc.port, dc.id,
                loggers=client._log, proxy=client._proxy,
            ))
            if key is None:
                # DC אחר מחייב ייצוא הרשאה — אבל רק פעם אחת. המפתח
                # שנוצר כאן משמש גם את שאר החיבורים, במקום לבצע ייצוא
                # נפרד לכל אחד מהם על החיבור הראשי
                auth = await client(functions.auth.ExportAuthorizationRequest(dc_id))
                init = copy.copy(client._init_request)
                init.query = functions.auth.ImportAuthorizationRequest(
                    id=auth.id, bytes=auth.bytes)
                await sender.send(functions.InvokeWithLayerRequest(LAYER, init))
                key = sender.auth_key
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

    done = 0
    lock = asyncio.Lock()
    handle = os.open(dst, os.O_WRONLY)
    senders = await asyncio.wait_for(
        _open_senders(client, dc_id, workers), timeout=config.TG_CONNECT_TIMEOUT)

    # כמה בקשות מותר להחזיק באוויר בו-זמנית, על פני כל החיבורים. זה
    # ולא מספר החיבורים הוא מה שקובע את הקצב, ואי אפשר לדעת מראש כמה
    # החשבון והקו מרשים — לכן מתחילים גבוה ומצטמצמים רק אם טלגרם מתלונן
    inflight = asyncio.Semaphore(workers * max(1, config.TG_PIPELINE))
    shrunk = 0

    async def shrink() -> None:
        """מוריד את התקרה אחרי FLOOD_WAIT, ולא מעלה אותה בחזרה.

        הפחתה כפלית: טלגרם כבר העניש אותנו, וניסיון לטפס חזרה מיד
        מחזיר אותנו לאותו מקום. מי שמחזיק את ההיתרים האלה לא משחרר
        אותם עד סוף ההורדה.
        """
        nonlocal shrunk
        room = workers * max(1, config.TG_PIPELINE) - shrunk
        drop = max(1, room // 2)
        for _ in range(drop):
            await inflight.acquire()
        shrunk += drop
        log.warning("התקרה ירדה ל-%d בקשות באוויר", room - drop)

    pending: asyncio.Queue[int] = asyncio.Queue()
    for index in range(total_parts):
        pending.put_nowait(index)
    last_progress = time.monotonic()

    async def fetch(sender, offset: int):
        """בקשה אחת, עם תקרת זמן וניסיונות חוזרים.

        בלי התקרה, חיבור שמפסיק לענות באמצע משאיר את העובד ממתין לנצח
        וההורדה נתקעת באחוז אקראי — בלי שגיאה, בלי לוג, בלי נפילה חזרה.
        """
        for attempt in range(1, config.TG_READ_RETRIES + 1):
            try:
                async with inflight:
                    return await asyncio.wait_for(
                        client._call(sender, functions.upload.GetFileRequest(
                            location, offset=offset, limit=part)),
                        timeout=config.TG_READ_TIMEOUT)
            except FloodWaitError as flood:
                # טלגרם אומר במפורש כמה להמתין. השהיה קצרה משלנו רק
                # מאריכה את העונש, ולכן ממתינים בדיוק כמה שנדרש. זה
                # נעשה קריטי ברגע שיש הרבה בקשות באוויר
                wait = min(float(flood.seconds) + 1, config.TG_FLOOD_MAX)
                if float(flood.seconds) > config.TG_FLOOD_MAX:
                    log.error("טלגרם ביקש להמתין %ds — יותר מהתקרה, "
                              "כדאי להוריד TG_PIPELINE", flood.seconds)
                    raise
                log.warning("טלגרם מגביל קצב, ממתינים %.0f שניות", wait)
                await shrink()
                await asyncio.sleep(wait)
                continue
            except asyncio.TimeoutError:
                log.warning("חלק ב-%d לא נענה תוך %.0f שניות (ניסיון %d/%d)",
                            offset, config.TG_READ_TIMEOUT, attempt,
                            config.TG_READ_RETRIES)
            except Exception as exc:  # noqa: BLE001
                log.warning("חלק ב-%d נכשל: %s (ניסיון %d/%d)",
                            offset, exc, attempt, config.TG_READ_RETRIES)
            if attempt == config.TG_READ_RETRIES:
                raise
            await asyncio.sleep(min(8, 2 ** attempt))

    async def pull(sender) -> None:
        """מושך חלקים מתור משותף, בקשה אחת בכל רגע.

        תור ולא טווח קבוע: חיבור שמת לא משאיר את החלקים שלו יתומים —
        מי שעדיין חי לוקח אותם.
        """
        nonlocal done, last_progress
        while True:
            try:
                index = pending.get_nowait()
            except asyncio.QueueEmpty:
                return
            offset = index * part
            try:
                result = await fetch(sender, offset)
            except Exception:  # noqa: BLE001 — שיקח אותו עובד אחר
                pending.put_nowait(index)
                raise
            if isinstance(result, types.upload.FileCdnRedirect):
                raise RuntimeError("טלגרם הפנה ל-CDN, אין תמיכה במסלול המהיר")
            block = bytes(result.bytes)[: max(0, size - offset)]
            if not block:
                continue
            os.pwrite(handle, block, offset)
            async with lock:
                done += len(block)
                last_progress = time.monotonic()
                if on_progress:
                    await on_progress(done, size)

    async def worker(sender) -> None:
        """כמה בקשות באוויר על אותו חיבור, ולא אחת בכל רגע.

        זה היה הצוואר האמיתי. בקשה אחת בכל רגע אומרת שהקצב נקבע בהשהיה
        ולא ברוחב הפס: חלק של 512KB חלקי זמן הלוך-חזור לטלגרם (כ-380
        אלפיות) נותן 1.35MB/s, וזה בדיוק מה שנמדד. הקו לא היה עמוס —
        הוא עמד ריק רוב הזמן וחיכה לתשובה.

        חיבור MTProto יחיד מסוגל להחזיק כמה שאילתות במקביל, ולכן ההכפלה
        כאן אינה דורשת עוד חיבורים — מה שגם מקטין את הסיכון ש-טלגרם
        יגביל קצב. בקשות באוויר = חיבורים × TG_PIPELINE.

        כשאחת מהבקשות נכשלת ה-gather מפיץ את החריגה החוצה, והחיבור
        מסומן כמת בדיוק כמו קודם — לוגיקת הסבבים שלמטה לא משתנה
        """
        await asyncio.gather(*(pull(sender)
                               for _ in range(max(1, config.TG_PIPELINE))))

    async def watchdog() -> None:
        """מכריז על תקיעה אם אף בייט לא ירד זמן רב."""
        while True:
            await asyncio.sleep(10)
            idle = time.monotonic() - last_progress
            if idle > config.TG_STALL_TIMEOUT:
                raise RuntimeError(
                    f"ההורדה תקועה {idle:.0f} שניות על {done * 100 // max(1, size)}%")

    try:
        log.info("מוריד ב-%d חיבורים × %d בקשות = %d באוויר, "
                 "חלק %dKB, %d חלקים (%.0fMB)",
                 workers, config.TG_PIPELINE, workers * config.TG_PIPELINE,
                 part // 1024, total_parts, size / 1048576)
        guard = asyncio.create_task(watchdog())
        healthy = list(senders)
        try:
            # סבבים: חיבור שמת מחזיר את החלק שלו לתור, ואם העובדים האחרים
            # כבר סיימו — סבב נוסף עם מי שנשאר חי לוקח אותו. בלי זה חיבור
            # אחד שנופל היה מכשיל את כל ההורדה
            while healthy and not pending.empty():
                outcomes = asyncio.gather(
                    *(worker(sender) for sender in healthy), return_exceptions=True)
                finished, _ = await asyncio.wait(
                    [asyncio.ensure_future(outcomes), guard],
                    return_when=asyncio.FIRST_COMPLETED)
                if guard in finished:
                    raise guard.exception() or RuntimeError("ההורדה תקועה")
                healthy = [sender for sender, result
                           in zip(healthy, await outcomes)
                           if not isinstance(result, BaseException)]
                if not pending.empty():
                    log.warning("%d חלקים חוזרים לסבב נוסף, %d חיבורים חיים",
                                pending.qsize(), len(healthy))
        finally:
            guard.cancel()
    finally:
        os.close(handle)
        await _close_senders(senders)

    # הגודל נקבע מראש ב-truncate, ולכן השוואת גודל לא בודקת כלום: חור
    # באמצע הקובץ היה עובר בשקט ומגיע למשתמש כווידאו פגום. נספרים
    # הבייטים שבאמת נכתבו
    if done != size:
        raise RuntimeError(f"ירדו {done} בייט מתוך {size} — הקובץ חסר")
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
            # תקרת זמן וניסיונות חוזרים, בדיוק כמו בהורדה: בלעדיהם חיבור
            # שמפסיק לענות היה תוקע את ההעלאה לנצח
            for attempt in range(1, config.TG_READ_RETRIES + 1):
                try:
                    await asyncio.wait_for(client._call(
                        sender, functions.upload.SaveBigFilePartRequest(
                            file_id=file_id, file_part=index,
                            file_total_parts=parts, bytes=block)),
                        timeout=config.TG_READ_TIMEOUT)
                    break
                except Exception as exc:  # noqa: BLE001
                    log.warning("חלק %d בהעלאה נכשל: %s (ניסיון %d/%d)",
                                index, type(exc).__name__, attempt,
                                config.TG_READ_RETRIES)
                    if attempt == config.TG_READ_RETRIES:
                        queue.put_nowait(index)
                        raise
                    await asyncio.sleep(min(8, 2 ** attempt))
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
