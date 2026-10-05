"""הורדת וידאו מקישור, עם אותן סטטיסטיקות כמו הורדה מטלגרם."""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import re
import shutil
import sys
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.I)
# תבנית שמוציאה מ-yt-dlp שורה אחת שקל לקרוא לכל עדכון
TEMPLATE = "zx %(progress.downloaded_bytes)s %(progress.total_bytes)s " \
           "%(progress.total_bytes_estimate)s %(progress.speed)s"


class FetchError(RuntimeError):
    pass


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


def _number(token: str) -> float:
    try:
        value = float(token)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if value != value else value


async def download(url: str, work: Path, on_progress=None) -> Path:
    """מוריד מקישור. cobalt קודם אם הוגדר, אחרת yt-dlp."""
    if config.COBALT_URL:
        try:
            return await _cobalt(url, work, on_progress)
        except FetchError as exc:
            log.warning("cobalt נכשל (%s), עוברים ל-yt-dlp", exc)
    return await _ytdlp(url, work, on_progress)


async def _cobalt(url: str, work: Path, on_progress=None) -> Path:
    """מוריד דרך שרת cobalt מקומי.

    יוטיוב חוסמים את yt-dlp מכתובות של שרתים ודורשים התחברות. cobalt
    שרץ אצלנו פותר את זה בלי מפתחות ובלי חשבון — שולחים לו קישור, הוא
    מחזיר כתובת הורדה ישירה.
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
                            await on_progress(done, total)
        except httpx.HTTPError as exc:
            target.unlink(missing_ok=True)
            raise FetchError(f"ההורדה מ-cobalt נקטעה: {exc}") from None

    if not target.exists() or target.stat().st_size < 1024:
        raise FetchError("cobalt החזיר קובץ ריק")
    log.info("הורד דרך cobalt: %s (%.1f MB)",
             target.name, target.stat().st_size / 1048576)
    return target


async def _ytdlp(url: str, work: Path, on_progress=None) -> Path:
    """מוריד את הווידאו הטוב ביותר שנכנס במגבלה, וממזג לקובץ אחד."""
    if not available():
        raise FetchError("yt-dlp לא מותקן על השרת. התקנה: pip install yt-dlp")

    target = work / "source.%(ext)s"
    cookies = Path(config.FETCH_COOKIES) if config.FETCH_COOKIES else None
    if cookies and not cookies.exists():
        log.warning("קובץ העוגיות לא נמצא ב-%s", cookies)
        cookies = None

    cmd = _command() + [
        "--no-playlist", "--newline",
        "--progress-template", TEMPLATE,
        "-f", config.FETCH_FORMAT,
        "--merge-output-format", "mp4",
        "--retries", "10", "--fragment-retries", "10",
        "--concurrent-fragments", str(config.FETCH_CONNECTIONS),
    ] + _aria2_args() + [
        "-o", str(target),
    ] + (["--cookies", str(cookies)] if cookies else []) + [url]
    log.info("מוריד מקישור: %s", url)

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

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
            await on_progress(done, total)

    _, err = await asyncio.gather(pump(), proc.stderr.read() if proc.stderr else _none())
    await proc.wait()

    if proc.returncode != 0:
        raise FetchError(_explain((err or b"").decode("utf-8", "replace")))

    files = sorted(work.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        raise FetchError("ההורדה הסתיימה אבל לא נוצר קובץ")
    log.info("הורד: %s (%.1f MB)", files[0].name, files[0].stat().st_size / 1048576)
    return files[0]


def _explain(stderr: str) -> str:
    """הופך את השגיאה של yt-dlp להסבר שאפשר לפעול לפיו.

    יוטיוב חסמו הורדות מכתובות של שרתים, והשגיאה הגולמית לא מסבירה מה
    לעשות. שלוש התקלות הנפוצות מקבלות כאן הסבר ופתרון.
    """
    log.error("yt-dlp נכשל:\n%s", stderr.strip()[-2000:])
    low = stderr.lower()

    if "confirm you" in low or "not a bot" in low or "sign in" in low:
        return ("יוטיוב דורש התחברות להורדה מהשרת הזה.\n"
                "צריך קובץ עוגיות מחשבון מחובר, ואז FETCH_COOKIES ב-.env.\n"
                "ההוראות ב-README תחת 'הורדה מיוטיוב'.")
    if "429" in low or "too many requests" in low:
        return ("יוטיוב חוסם זמנית את כתובת השרת (429). נסה שוב בעוד "
                "כמה דקות, או הוסף קובץ עוגיות ב-FETCH_COOKIES.")
    if "failed to extract" in low or "player response" in low:
        return ("yt-dlp לא הצליח לקרוא את הנגן של יוטיוב — הגרסה שמותקנת "
                "ישנה מדי.\n"
                "עדכון: pip install -U --pre \"yt-dlp[default]\"")
    if "javascript runtime" in low:
        return ("yt-dlp דורש סביבת JavaScript להורדה מיוטיוב.\n"
                "התקנה: curl -fsSL https://deno.land/install.sh | sh")
    if "unsupported url" in low:
        return "הקישור הזה לא נתמך."
    if "private video" in low or "members-only" in low:
        return "הסרטון פרטי או למנויים בלבד."

    lines = [l for l in stderr.strip().splitlines() if l.strip()]
    return "\n".join(lines[-4:]) or "ההורדה מהקישור נכשלה"


async def _none() -> bytes:
    return b""
