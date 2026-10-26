"""הורדת וידאו מקישור, עם אותן סטטיסטיקות כמו הורדה מטלגרם."""
from __future__ import annotations

import asyncio
import time
import pathlib
import os
import importlib.util
import json
import logging
import urllib.parse
import re
import shutil
import sys
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.I)
# תבנית שמוציאה מ-yt-dlp שורה אחת שקל לקרוא לכל עדכון
TEMPLATE = "zx %(progress.downloaded_bytes)s %(progress.total_bytes)s " \
           "%(progress.total_bytes_estimate)s %(progress.speed)s " \
           "%(progress.eta)s"


class FetchError(RuntimeError):
    pass


class StalePlayer(FetchError):
    """הכישלון נבע מגרסה ישנה, ו-yt-dlp עודכן זה עתה.

    נפרד מ-FetchError כדי שהקורא יידע שיש טעם בניסיון נוסף. המודול
    שכבר נטען לזיכרון נשאר ישן, אבל ההרצה היא תת-תהליך ולכן הניסיון
    הבא כבר מקבל את הגרסה החדשה
    """


def find_url(text: str) -> str | None:
    match = URL_PATTERN.search(text or "")
    return match.group(0) if match else None


def available() -> bool:
    """yt-dlp מותקן כחבילה בסביבה, לא בהכרח כפקודה ב-PATH."""
    return importlib.util.find_spec("yt_dlp") is not None or \
        shutil.which("yt-dlp") is not None


def _command() -> list[str]:
    """מריץ דרך אותו פייתון, כדי לא להיות תלויים ב-PATH של השירות."""
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    return ["yt-dlp"]


def _is_youtube(url: str) -> bool:
    """האם זה קישור יוטיוב. שם חלים כללים אחרים לגמרי."""
    host = urllib.parse.urlsplit(url).netloc.lower()
    return any(part in host for part in
               ("youtube.com", "youtu.be", "youtube-nocookie.com"))


def _is_drive(url: str) -> bool:
    """האם זה קישור לקובץ בגוגל דרייב."""
    host = urllib.parse.urlsplit(url).netloc.lower()
    return any(part in host for part in
               ("drive.google.com", "drive.usercontent.google.com",
                "docs.google.com"))


def _format_for(url: str, fmt: str = "") -> str:
    """בורר התבנית לקישור הזה.

    בדרייב זה לא עניין של טעם. המחלץ של yt-dlp מציע שני סוגים:
    הזרמים שגוגל מקודדת מחדש בשביל הנגן שלה, ובנוסף תבנית אחת
    בשם source — הקובץ המקורי עצמו. לזרמי הנגן יש height, vcodec
    ו-acodec, ול-source אין אף אחד מהם (נבדק במקור של המחלץ:
    googledrive.py, הוא מוסיף ל-source רק url, ext ו-quality).

    התבנית שלנו היא bestvideo[height<=1080]+bestaudio/best[...]/best,
    וכל איבר בה דורש height או vcodec — כלומר source נפסל תמיד,
    ובדרייב ירדו אצלנו **זרמי הנגן** ולא הקובץ. זה מסביר את הכל:
    ‏"אין בזה איכויות", ההורדה שנתקעת על קצב של פחות ממגה־בייט
    (ה-CDN של הנגן מצומצם, ולא זה של הקבצים), ואותו קובץ שיורד
    בטלפון בדקות — הטלפון מוריד את הקובץ, אנחנו הורדנו תמלול וידאו.

    המחלץ גם כופה על זרמי הנגן http_chunk_size של 10MB, כלומר
    בקשות טווח טוריות, וזה מבטל את ההורדה המקבילית לגמרי
    """
    if _is_drive(url):
        return config.FETCH_FORMAT_DRIVE
    return fmt or config.FETCH_FORMAT


def _browser_args(url: str) -> list[str]:
    """כותרות שגורמות לבקשה להיראות כמו דפדפן.

    רשתות הפצה חוסמות בקשה שאינה נראית כך. נמדד על קישור m3u8 שעבד
    בכל דפדפן וחזר כאן כ-"HTTP Error 403: Forbidden": ‏yt-dlp שולח
    User-Agent משלו ואינו שולח Referer כלל, ורוב ה-CDN בודקים בדיוק
    את השניים האלה.

    ביוטיוב לא נוגעים: שם ה-UA חלק מזרימת ה-PO token, ושינוי שלו
    שובר מסלול שעובד
    """
    args: list[str] = []
    if config.FETCH_PROXY:
        # הפרוקסי חל על כל קישור, גם יוטיוב: החסימה היא על ה-IP של
        # השרת ולא על האתר הספציפי
        args += ["--proxy", config.FETCH_PROXY]
    if _is_youtube(url):
        return args
    where = urllib.parse.urlsplit(url)
    origin = (config.FETCH_REFERER
              or (f"{where.scheme}://{where.netloc}/"
                  if where.scheme and where.netloc else ""))
    if config.FETCH_UA:
        args += ["--user-agent", config.FETCH_UA]
    if origin:
        args += ["--referer", origin,
                 "--add-header", f"Origin:{origin.rstrip('/')}"]
    return args


def _aria2_args() -> list[str]:
    """מעביר את ההורדה ל-aria2c אם הוא מותקן.

    aria2c פותח כמה חיבורים לאותו קובץ ומנצל את הקו טוב יותר מההורדה
    הפנימית של yt-dlp. זה לא עוקף את רוחב הפס של השרת — רק מתקרב אליו.
    """
    if config.FETCH_ARIA2 in ("0", "off", "no", ""):
        return []
    if not shutil.which("aria2c"):
        if config.FETCH_ARIA2 not in ("auto", "1", "on", "yes"):
            log.warning("aria2c אינו מותקן — ממשיכים בהורדה הפנימית")
        return []
    count = max(1, config.ARIA2_CONNECTIONS)
    return [
        "--downloader", "aria2c",
        "--downloader-args",
        f"aria2c:-x{count} -s{count} -k1M --file-allocation=none "
        "--console-log-level=warn",
    ]


# שמות הקבצים החלקיים שכל מוריד משאיר אחריו בדרך
_PARTIALS = ("source.*", "*.part", "*.frag", "*.ytdl", "*.aria2")


def disk_bytes(work: Path) -> int:
    """כמה בייטים באמת יושבים על הדיסק בתיקיית העבודה.

    זה מקור האמת כשהמוריד עצמו שותק: aria2c הוא תת-תהליך חיצוני,
    ו-yt-dlp אינו מדווח עליו דרך --progress-template בכלל. בלי זה
    המסך קופא על "מוריד" לאורך כל ההורדה וזה נראה כמו תקיעה
    """
    # התבניות חופפות — source.mp4.part תופס גם את source.* וגם את
    # ‏*.part — ובלי איחוד הגודל נספר פעמיים
    sizes = {}
    for pattern in _PARTIALS:
        for path in work.glob(pattern):
            try:
                sizes[path] = path.stat().st_size
            except OSError:
                continue
    return sum(sizes.values())


def _number(token: str) -> float:
    try:
        value = float(token)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if value != value else value


async def heights(url: str, timeout: float = 45.0) -> list[int]:
    """הרזולוציות שבאמת קיימות בקישור, מהגבוהה לנמוכה.

    רשימה קבועה היא ניחוש: לסרטון אחד יש 1080p ולאחר רק 360p, ולהציע
    למשתמש איכות שאינה קיימת זה להבטיח לו משהו שלא יקבל. yt-dlp כבר
    יודע מה יש — שואלים אותו.

    כישלון אינו מפיל כלום: הקורא נופל לרשימה הקבועה
    """
    cmd = _command() + _browser_args(url) + [
        "-J", "--no-warnings", "--no-playlist", url]
    if config.FETCH_COOKIES:
        cmd += ["--cookies", config.FETCH_COOKIES]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=child_env())
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, OSError) as exc:
        log.warning("בדיקת איכויות נכשלה (%s)", exc)
        return []
    if proc.returncode != 0 or not out:
        return []
    try:
        info = json.loads(out.decode("utf-8", "replace"))
    except ValueError:
        return []

    found = set()
    for item in info.get("formats") or ():
        # רק מסלולי וידאו אמיתיים. מסלול שמע נקי מדווח vcodec="none"
        if (item.get("vcodec") or "none") == "none":
            continue
        tall = item.get("height")
        if isinstance(tall, int) and tall > 0:
            found.add(tall)
    ordered = sorted(found, reverse=True)
    log.info("איכויות זמינות בקישור: %s",
             ", ".join(f"{h}p" for h in ordered) or "לא נמצאו")
    return ordered


def format_for(quality: str) -> str:
    """בוחר תבנית yt-dlp לפי הרזולוציה שהמשתמש ביקש.

    "best" מוריד את הקיים הטוב ביותר, כולל 4K. כל השאר תוקרה בגובה,
    עם נפילה אחורה לכל מה שקיים — אחרת סרטון שאין לו את הרזולוציה
    המדויקת פשוט נכשל במקום לרדת דרגה
    """
    if not quality or quality == "best":
        return "bestvideo+bestaudio/best" if quality else config.FETCH_FORMAT
    if not quality.isdigit():
        return config.FETCH_FORMAT
    return (f"bestvideo[height<={quality}]+bestaudio/"
            f"best[height<={quality}]/best")


async def download(url: str, work: Path, on_progress=None,
                   fmt: str = "") -> Path:
    """מוריד מקישור. cobalt קודם אם הוגדר, אחרת yt-dlp."""
    if config.COBALT_URL:
        try:
            return await _cobalt(url, work, on_progress)
        except FetchError as exc:
            log.warning("cobalt נכשל (%s), עוברים ל-yt-dlp", exc)
    try:
        return await _ytdlp(url, work, on_progress, fmt)
    except StalePlayer:
        # yt-dlp עודכן באמצע הכישלון. ניסיון אחד נוסף, ורק אחד:
        # אם גם הגרסה החדשה נכשלת זו כבר לא בעיית גרסה
        log.warning("מנסה שוב עם הגרסה המעודכנת")
        for leftover in work.glob("source.*"):
            leftover.unlink(missing_ok=True)
        return await _ytdlp(url, work, on_progress, fmt)


async def _cobalt(url: str, work: Path, on_progress=None) -> Path:
    """מוריד דרך שרת cobalt מקומי.

    שולחים לו קישור, הוא מחזיר כתובת הורדה ישירה.

    B14: כאן היה כתוב ש-cobalt "פותר את זה בלי מפתחות ובלי חשבון". זה
    כבר לא מדויק ליוטיוב: גם cobalt נתקל היום בדרישת "הוכח שאינך בוט",
    וה-README שלו עצמו ממליץ לחבר אליו שרת PO token. הוא עדיין שווה
    כמסלול ראשון — הוא מצליח בחלק מהמקרים שבהם yt-dlp נכשל, ונפילה
    ממנו ל-yt-dlp היא מיידית — אבל אינו פתרון קסם, ועדיף שזה יהיה
    כתוב מאשר שיתגלה בשטח.
    """
    import httpx

    body = {
        "url": url,
        "videoQuality": config.COBALT_QUALITY,
        "filenameStyle": "basic",
        "downloadMode": "auto",
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=20.0)) as http:
        try:
            answer = await http.post(config.COBALT_URL + "/", json=body,
                                     headers=headers)
            data = answer.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FetchError(f"שרת cobalt לא הגיב: {exc}") from None

        status = data.get("status")
        if status == "error":
            code = (data.get("error") or {}).get("code", "")
            raise FetchError(f"cobalt סירב: {code or data}")
        if status == "picker":
            items = [i for i in data.get("picker", []) if i.get("type") != "photo"]
            if not items:
                raise FetchError("cobalt החזיר רק תמונות")
            link, name = items[0].get("url"), "source.mp4"
        elif status in ("tunnel", "redirect", "local-processing"):
            link = data.get("url") or next(iter(data.get("tunnel") or []), None)
            name = data.get("filename") or "source.mp4"
        else:
            raise FetchError(f"תשובה לא מוכרת מ-cobalt: {status}")
        if not link:
            raise FetchError("cobalt לא החזיר כתובת הורדה")

        suffix = Path(name).suffix or ".mp4"
        target = work / f"source{suffix}"
        done = 0
        log.info("מוריד דרך cobalt: %s", name)
        try:
            async with http.stream("GET", link) as stream:
                stream.raise_for_status()
                total = int(stream.headers.get("content-length") or 0)
                with target.open("wb") as fh:
                    async for block in stream.aiter_bytes(1024 * 256):
                        fh.write(block)
                        done += len(block)
                        if on_progress:
                            await on_progress(done, total, 0.0)
        except httpx.HTTPError as exc:
            target.unlink(missing_ok=True)
            raise FetchError(f"ההורדה מ-cobalt נקטעה: {exc}") from None

    if not target.exists() or target.stat().st_size < 1024:
        raise FetchError("cobalt החזיר קובץ ריק")
    log.info("הורד דרך cobalt: %s (%.1f MB)",
             target.name, target.stat().st_size / 1048576)
    return target


# מפסק זרם: אחרי כמה כשלונות רצופים אין טעם להמשיך לדפוק על אותה דלת.
# יוטיוב מחמירה את החסימה כשממשיכים לנסות, ולכן עדיף לעצור, להודיע
# בבירור, ולתת לזה לנוח
_failures = 0
_blocked_until = 0.0


def _breaker_open() -> float:
    """כמה שניות נותרו לחסימה העצמית, או 0 אם פתוח."""
    return max(0.0, _blocked_until - time.monotonic())


def _note_failure() -> None:
    global _failures, _blocked_until
    _failures += 1
    if _failures >= config.FETCH_BREAKER_FAILS:
        _blocked_until = time.monotonic() + config.FETCH_BREAKER_REST
        log.warning("%d כשלונות רצופים — עוצרים הורדות מקישור ל-%.0f דקות",
                    _failures, config.FETCH_BREAKER_REST / 60)


def _note_success() -> None:
    global _failures, _blocked_until
    _failures = 0
    _blocked_until = 0.0


async def _ytdlp(url: str, work: Path, on_progress=None,
                 fmt: str = "") -> Path:
    """מוריד את הווידאו הטוב ביותר שנכנס במגבלה, וממזג לקובץ אחד."""
    if not available():
        raise FetchError("yt-dlp לא מותקן על השרת. התקנה: pip install yt-dlp")
    rest = _breaker_open()
    if rest:
        raise FetchError(
            f"יוטיוב חוסמת את השרת כרגע. ניסינו {config.FETCH_BREAKER_FAILS} "
            f"פעמים ברצף ונכשלנו, ולכן ההורדות מקישור מושהות עוד "
            f"{rest / 60:.0f} דקות כדי לא להחמיר את החסימה.\n"
            "בינתיים אפשר לשלוח את הקובץ ישירות לבוט.")

    target = work / "source.%(ext)s"
    cookies = Path(config.FETCH_COOKIES) if config.FETCH_COOKIES else None
    if cookies and not cookies.exists():
        log.warning("קובץ העוגיות לא נמצא ב-%s", cookies)
        cookies = None

    cmd = _command() + _browser_args(url) + [
        # --no-config: קובץ הגדרות אישי בשרת שינה התנהגות בלי שאיש ידע.
        # -4: רזולוציית IPv6 נכשלת בשקט אצל חלק מהספקים ועולה בזמן.
        # player_client: הלקוח שיוטיוב מגישה לו את הנגן. הערכים משתנים
        # מגרסה לגרסה, ולכן הוא ניתן להגדרה ולא מוטבע בקוד
        "--no-config", "-4",
        "--extractor-args", f"youtube:player_client={config.FETCH_CLIENTS}",
        "--no-playlist", "--newline",
        "--progress-template", TEMPLATE,
        "-f", _format_for(url, fmt),
        "--merge-output-format", "mp4",
        "--retries", "10", "--fragment-retries", "10",
        "--concurrent-fragments", str(config.FETCH_CONNECTIONS),
    ] + (["--extractor-args",
          f"youtubepot-bgutilhttp:base_url={config.FETCH_POT_URL}"]
         if config.FETCH_POT_URL else []
         ) + _aria2_args() + [
        "-o", str(target),
    ] + (["--cookies", str(cookies)] if cookies else []) + [url]
    log.info("מוריד מקישור: %s", url)
    # איזה מוריד באמת פועל קובע אם ההתקדמות מדווחת מהמוריד או מהדיסק,
    # ובלי השורה הזאת אין דרך לדעת זאת מהלוג
    log.info("מוריד: %s · חלקים במקביל: %s · תבנית: %s",
             "aria2c" if "--downloader" in cmd else "פנימי של yt-dlp",
             config.FETCH_CONNECTIONS, _format_for(url, fmt))

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=child_env(),
    )

    # מצב משותף בין המוריד לשעון הדיסק: מתי דווח לאחרונה וכמה בסך הכל
    seen = {"at": 0.0, "total": 0.0}

    async def pump() -> None:
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("zx ") or not on_progress:
                if line and not line.startswith("zx "):
                    log.debug("yt-dlp: %s", line[:120])
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            done = _number(parts[1])
            total = _number(parts[2]) or _number(parts[3])
            # ה-ETA של yt-dlp מחושב על הקצב שלו עצמו, והוא מדויק
            # יותר מהערכה שנבנה מבחוץ על ממוצע נע
            eta = _number(parts[5]) if len(parts) > 5 else 0.0
            seen["at"] = time.monotonic()
            seen["total"] = total or seen["total"]
            await on_progress(done, total, eta)

    async def watch() -> None:
        """מדווח מהדיסק כשהמוריד שותק, ומזהה תקיעה אמיתית."""
        if not on_progress:
            return
        grew_at = time.monotonic()
        most = 0
        while proc.returncode is None:
            await asyncio.sleep(config.FETCH_WATCH_EVERY)
            now = time.monotonic()
            if now - seen["at"] < config.FETCH_WATCH_EVERY * 2.5:
                continue        # המוריד מדווח בעצמו — לא מתערבים
            done = disk_bytes(work)
            if done > most:
                most, grew_at = done, now
            note = ""
            idle = now - grew_at
            if idle > config.FETCH_STALL:
                note = f"לא זז {int(idle)}ש"
            try:
                await on_progress(done, seen["total"], 0.0, note)
            except asyncio.CancelledError:
                raise
            except Exception as exc:        # noqa: BLE001
                log.debug("דיווח מהדיסק נכשל: %s", exc)

    watcher = asyncio.ensure_future(watch())
    try:
        _, err = await asyncio.gather(
            pump(), proc.stderr.read() if proc.stderr else _none())
        await proc.wait()
    finally:
        watcher.cancel()

    if proc.returncode != 0:
        stderr = (err or b"").decode("utf-8", "replace")
        # רק חסימה אמיתית מקדמת את המפסק. קישור שגוי או סרטון פרטי הם
        # כישלון של הבקשה הזו ולא סימן שיוטיוב חוסמת את השרת
        if _is_block(stderr):
            _note_failure()
        if _stale_player(stderr) and await update_nightly():
            raise StalePlayer(_explain(stderr, url))
        raise FetchError(_explain(stderr, url))

    files = sorted(work.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        raise FetchError("ההורדה הסתיימה אבל לא נוצר קובץ")
    _note_success()
    log.info("הורד: %s (%.1f MB)", files[0].name, files[0].stat().st_size / 1048576)
    return files[0]


# מקומות התקנה מקובלים של deno, מעבר למה שנמצא ב-PATH
_DENO_DIRS = ("~/.deno/bin", "/usr/local/bin", "/opt/deno/bin", "/root/.deno/bin")


def deno_dir() -> str:
    """היכן נמצא deno, או מחרוזת ריקה אם אינו מותקן.

    B15: deno מותקן כברירת מחדל ל-~/.deno/bin, וה-PATH של systemd אינו
    כולל אותה. yt-dlp מדווח אז "אין סביבת JavaScript" אף שהכלי מותקן
    ועובד מצוין מהטרמינל — תקלה שנראית כמו חסימה של יוטיוב ואינה כזו.
    """
    found = shutil.which("deno")
    if found:
        return str(pathlib.Path(found).parent)
    for raw in _DENO_DIRS:
        candidate = pathlib.Path(raw).expanduser() / "deno"
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate.parent)
    return ""


def deno_ready() -> bool:
    return bool(deno_dir())


def child_env() -> dict:
    """סביבה לתהליכי הבן, עם deno ב-PATH גם כשה-שירות לא יודע עליו."""
    env = dict(os.environ)
    extra = deno_dir()
    if extra and extra not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = extra + os.pathsep + env.get("PATH", "")
    return env


# סימנים לכך שיוטיוב חוסמת את השרת, להבדיל מתקלה בבקשה עצמה
_BLOCK_SIGNS = ("sign in to confirm", "not a bot", "429", "too many requests",
                "failed to extract", "player response", "po token",
                "unable to download api page")


# סימנים לכך שהגרסה המותקנת ישנה ולא שהבקשה שגויה. יוטיוב משנה את
# הנגן כל כמה ימים, והתיקון נכנס ל-nightly תוך שעות
_STALE_SIGNS = (
    "failed to extract", "player response", "unable to extract",
    "nsig extraction failed", "signature extraction failed",
    "please report this issue", "update to the latest version",
)
_updated_at = 0.0


def _stale_player(stderr: str) -> bool:
    low = stderr.lower()
    return any(sign in low for sign in _STALE_SIGNS)


async def update_nightly() -> bool:
    """מעדכן את yt-dlp לערוץ nightly. מחזיר אם העדכון הצליח.

    ‏nightly ולא יציב: יוטיוב שוברת את הנגן כל כמה ימים, התיקון נכנס
    לערוץ הזה תוך שעות ולערוץ היציב רק אחרי שבועות. זה גם מה שהתיעוד
    של yt-dlp ממליץ למי שמוריד מיוטיוב.

    מרווח מינימלי בין ניסיונות, אחרת כל הורדה שנכשלת מריצה pip.
    """
    global _updated_at
    if not config.YTDLP_AUTO_UPDATE:
        return False
    now = time.monotonic()
    if _updated_at and now - _updated_at < config.YTDLP_UPDATE_EVERY:
        log.info("עדכון yt-dlp דולג — עודכן לפני %.0f דקות",
                 (now - _updated_at) / 60)
        return False
    _updated_at = now

    log.warning("יוטיוב שברה את הנגן — מעדכן את yt-dlp לערוץ nightly")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "install", "-U", "--pre",
        "--disable-pip-version-check", "yt-dlp[default]",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = (out or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        log.error("עדכון yt-dlp נכשל:\n%s", text.strip()[-800:])
        return False

    # הגרסה החדשה נטענת רק בתהליך חדש. המודול שכבר מיובא נשאר ישן,
    # ולכן ההרצה הבאה חייבת להיות כתת-תהליך — וכך זה ממילא עובד כאן
    line = next((x for x in text.splitlines()
                 if "Successfully installed" in x), "")
    log.warning("yt-dlp עודכן. %s", line.strip() or "ללא שינוי גרסה")
    return "Successfully installed" in text


def _is_block(stderr: str) -> bool:
    low = stderr.lower()
    return any(sign in low for sign in _BLOCK_SIGNS)


def _explain(stderr: str, url: str = "") -> str:
    """הופך את השגיאה של yt-dlp להסבר שאפשר לפעול לפיו.

    יוטיוב חסמו הורדות מכתובות של שרתים, והשגיאה הגולמית לא מסבירה מה
    לעשות. שלוש התקלות הנפוצות מקבלות כאן הסבר ופתרון.

    ההסברים של יוטיוב חלים על קישורי יוטיוב בלבד. בלי התנאי הזה
    קישור שנכשל מסיבה אחרת לגמרי קיבל הסבר על PO token ועל עוגיות
    של יוטיוב — נמדד אצל המשתמש על קישור HLS שאין לו שום קשר אליה,
    והוא שלח אותו לרדוף אחרי פתרון שאינו קשור לתקלה
    """
    log.error("yt-dlp נכשל:\n%s", stderr.strip()[-2000:])
    low = stderr.lower()
    tube = _is_youtube(url) if url else True

    if tube and ("sign in" in low or "confirm you" in low
            or "not a bot" in low or "po token" in low):
        if config.FETCH_POT_URL:
            return ("יוטיוב דורשת אימות שאינך בוט, וגם שרת ה-PO token "
                    f"שהוגדר ({config.FETCH_POT_URL}) לא עזר. ודא שהוא רץ, "
                    "או הוסף קובץ עוגיות ב-FETCH_COOKIES.")
        return ("יוטיוב דורשת אימות שאינך בוט מכתובות של שרתים.\n"
                "שלוש דרכים, מהקלה לכבדה:\n"
                "1. לשלוח את הקובץ ישירות לבוט במקום קישור\n"
                "2. להפעיל שרת PO token ולהצביע עליו ב-FETCH_POT_URL:\n"
                "   docker run -d --name bgutil-provider -p 4416:4416 \\\n"
                "     brainicism/bgutil-ytdlp-pot-provider\n"
                "   FETCH_POT_URL=http://127.0.0.1:4416\n"
                "3. לייצא עוגיות מדפדפן מחובר ולהצביע ב-FETCH_COOKIES")
    if tube and ("429" in low or "too many requests" in low):
        return ("יוטיוב חוסם זמנית את כתובת השרת (429). נסה שוב בעוד "
                "כמה דקות, או הוסף קובץ עוגיות ב-FETCH_COOKIES.")
    if tube and ("failed to extract" in low or "player response" in low):
        return ("yt-dlp לא הצליח לקרוא את הנגן של יוטיוב — הגרסה שמותקנת "
                "ישנה מדי.\n"
                "עדכון: pip install -U --pre \"yt-dlp[default]\"")
    if "javascript runtime" in low:
        if deno_ready():
            return ("deno מותקן ב-" + deno_dir() + " אבל yt-dlp עדיין לא "
                    "מצא סביבת JavaScript. ודא שהשירות הופעל מחדש אחרי "
                    "ההתקנה.")
        return ("yt-dlp דורש סביבת JavaScript להורדה מיוטיוב, ו-deno "
                "אינו מותקן.\nהתקנה: curl -fsSL https://deno.land/install.sh | sh"
                "\nואז: systemctl restart zovexsub")
    if _is_drive(url) and ("too many users have viewed" in low
                           or "quota" in low
                           or "no video formats found" in low):
        # המכסה של דרייב היא על הקובץ ועל בעליו, לא על המוריד. היא
        # חוסמת בדיוק את מסלול הקובץ (source), ולכן yt-dlp נשאר בלי
        # שום תבנית ומדווח "No video formats found" — הודעה שאינה
        # מרמזת על הסיבה האמיתית ושולחת לפתוח באג
        return ("גוגל דרייב חסמה את הקובץ הזה במכסת הורדות: הוא נצפה "
                "או הורד יותר מדי בזמן קצר. זה על הקובץ עצמו ועל מי "
                "שהעלה אותו, ולא על השרת שלנו — ולכן גם החלפת IP או "
                "פרוקסי לא תעזור.\n"
                "שלוש דרכים, מהקלה לכבדה:\n"
                "1. לשלוח את הקובץ ישירות לבוט במקום קישור\n"
                "2. לפתוח את הקישור בדרייב, לעשות \"צור עותק\" "
                "לדרייב שלך, ולשלוח את הקישור לעותק — למכסה של "
                "העותק החדש אין היסטוריה\n"
                "3. לחכות. דרייב משחררת את המכסה תוך 24 שעות")
    if "403" in low or "forbidden" in low:
        # נמדד: curl חשוף מהשרת מקבל 403, ואותו קישור בדיוק עובר
        # מטלפון סלולרי באותה עיר. רשתות הפצה חוסמות טווחי אחסון
        # בלי קשר למדינה, והמסנן פועל לפני שהבקשה נקראת — ולכן אין
        # כותרת, גרסה או דגל שמשנים את זה
        if config.FETCH_PROXY:
            return ("האתר חוסם את הבקשה (403), גם דרך הפרוקסי שהוגדר "
                    f"({config.FETCH_PROXY}). ייתכן שגם הוא מזוהה "
                    "ככתובת של שרת.")
        return ("האתר חוסם את כתובת השרת (403).\n"
                "זו חסימה לפי סוג הרשת ולא לפי מדינה: ספקי אחסון "
                "חסומים, רשתות ביתיות וסלולריות לא. לכן אותו קישור "
                "עובד בטלפון ונכשל כאן.\n"
                "אפשרויות:\n"
                "1. להוריד במכשיר ולשלוח את הקובץ לבוט\n"
                "2. להגדיר FETCH_PROXY לכתובת פרוקסי ברשת ביתית")
    if "unsupported url" in low:
        return "הקישור הזה לא נתמך."
    if "private video" in low or "members-only" in low:
        return "הסרטון פרטי או למנויים בלבד."

    lines = [l for l in stderr.strip().splitlines() if l.strip()]
    return "\n".join(lines[-4:]) or "ההורדה מהקישור נכשלה"


async def _none() -> bytes:
    return b""
