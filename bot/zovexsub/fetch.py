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


def _number(token: str) -> float:
    try:
        value = float(token)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if value != value else value


async def download(url: str, work: Path, on_progress=None) -> Path:
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
