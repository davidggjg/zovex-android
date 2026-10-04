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
    cmd = _command() + [
        "--no-playlist", "--no-warnings", "--newline",
        "--progress-template", TEMPLATE,
        "-f", config.FETCH_FORMAT,
        "--merge-output-format", "mp4",
        "--retries", "10", "--fragment-retries", "10",
        "--concurrent-fragments", str(config.FETCH_CONNECTIONS),
        "-o", str(target), url,
    ]
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
        message = (err or b"").decode("utf-8", "replace").strip().splitlines()
        raise FetchError("\n".join(message[-4:]) or "ההורדה מהקישור נכשלה")

    files = sorted(work.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        raise FetchError("ההורדה הסתיימה אבל לא נוצר קובץ")
    log.info("הורד: %s (%.1f MB)", files[0].name, files[0].stat().st_size / 1048576)
    return files[0]


async def _none() -> bytes:
    return b""
