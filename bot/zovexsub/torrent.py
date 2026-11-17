"""הורדה מטורנט: קובץ ‎.torrent או קישור magnet.

מורידים עם aria2c, שכבר מותקן בשרת בשביל yt-dlp. אין שיתוף אחרי
הסיום (‎--seed-time=0): ברגע שהקבצים שלמים aria2c יוצא, והתיקייה
נמחקת בסוף העבודה יחד עם כל תיקיית העבודה.

אחרי ההורדה הסרטון הגדול ביותר הופך ל-source, וכל השאר — כתוביות,
תמונות, nfo — נאספים לתיקייה נפרדת כדי שהבוט ישלח אותם למשתמש. הוא
מחליט אם להשתמש בכתוביות שבאו עם הטורנט או בקובץ משלו.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

PREFIX = "torrent:"
VIDEO = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".webm", ".ts", ".wmv"}
# מה שנשלח למשתמש. סרטונים נוספים (sample, פרקים אחרים) אינם נשלחים:
# הם גדולים, והמשתמש ביקש את הקבצים הנלווים ולא עוד וידאו
EXTRA = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".sup",
         ".jpg", ".jpeg", ".png", ".webp", ".nfo", ".txt"}
EXTRA_MAX = 50 * 1024 * 1024
EXTRAS_DIR = "torrent-extras"

# [#2089b0 120MiB/1.2GiB(10%) CN:30 SD:5 DL:5.2MiB ETA:3m20s]
_LINE = re.compile(
    r"\[#\w+\s+([\d.]+)([KMG]i)?B/([\d.]+)([KMG]i)?B\((\d+)%\)"
    r"(?:.*?CN:(\d+))?(?:.*?SD:(\d+))?(?:.*?DL:([\d.]+)([KMG]i)?B)?(?:.*?ETA:(\w+))?")
_UNIT = {None: 1, "Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3}


class TorrentError(RuntimeError):
    pass


def is_torrent(url: str) -> bool:
    text = (url or "").strip().lower()
    return text.startswith("magnet:") or text.startswith(PREFIX)


def find_magnet(text: str) -> str | None:
    match = re.search(r"magnet:\?[^\s<>\"']+", text or "", re.I)
    return match.group(0) if match else None


def _seconds(eta: str | None) -> float:
    if not eta:
        return 0.0
    total = 0
    for value, unit in re.findall(r"(\d+)([hms])", eta):
        total += int(value) * {"h": 3600, "m": 60, "s": 1}[unit]
    return float(total)


def parse(line: str):
    """(הורד, סה"כ, מהירות, זמן נותר, מקורות) מתוך שורת סיכום של aria2c."""
    m = _LINE.search(line)
    if not m:
        return None
    done = float(m.group(1)) * _UNIT[m.group(2)]
    total = float(m.group(3)) * _UNIT[m.group(4)]
    speed = float(m.group(8)) * _UNIT[m.group(9)] if m.group(8) else 0.0
    peers = int(m.group(7) or m.group(6) or 0)   # מקורות, או חיבורים
    return done, total, speed, _seconds(m.group(10)), peers


def pick(folder: Path) -> tuple[Path | None, list[Path]]:
    """הסרטון הגדול ביותר, ורשימת הקבצים הנלווים שכדאי לשלוח."""
    files = [p for p in folder.rglob("*") if p.is_file()
             and not p.name.endswith(".aria2")]
    videos = [p for p in files if p.suffix.lower() in VIDEO]
    video = max(videos, key=lambda p: p.stat().st_size) if videos else None
    extras = sorted((p for p in files if p.suffix.lower() in EXTRA
                     and p.stat().st_size <= EXTRA_MAX),
                    key=lambda p: str(p).lower())
    return video, extras


async def download(url: str, work: Path, on_progress=None) -> Path:
    """מוריד את הטורנט ומחזיר את הסרטון. הנלווים נשארים ב-EXTRAS_DIR."""
    if not shutil.which("aria2c"):
        raise TorrentError("aria2c אינו מותקן בשרת: apt install -y aria2")
    target = url[len(PREFIX):] if url.lower().startswith(PREFIX) else url
    folder = work / "torrent"
    folder.mkdir(parents=True, exist_ok=True)
    args = [
        "aria2c", f"--dir={folder}",
        "--seed-time=0",                 # לא משתפים אחרי הסיום
        "--bt-save-metadata=false",
        "--follow-torrent=mem", "--file-allocation=none",
        "--enable-dht=true", "--bt-enable-lpd=true",
        f"--bt-stop-timeout={config.TORRENT_STALL}",
        f"--max-overall-upload-limit={config.TORRENT_UPLOAD_LIMIT}",
        "--summary-interval=2", "--console-log-level=warn",
        "--show-console-readout=true", target,
    ]
    from .fetch import kill_tree
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, start_new_session=True)
    tail: list[str] = []
    try:
        buffer = b""
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            buffer += chunk
            parts = re.split(rb"[\r\n]", buffer)
            buffer = parts.pop()
            for raw in parts:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                tail = (tail + [line])[-15:]
                got = parse(line)
                if got and on_progress and got[1] > 0:
                    done, total, speed, eta, seeds = got
                    note = (f"{seeds} מקורות" if seeds else "מחפש מקורות…")
                    await on_progress(done, total, eta, note)
        code = await proc.wait()
    finally:
        kill_tree(proc)
    if code != 0:
        log.warning("aria2c יצא עם קוד %s: %s", code, " | ".join(tail[-5:]))
        why = ("אין מקורות פעילים לטורנט הזה" if code in (2, 7)
               else f"aria2c נכשל (קוד {code})")
        raise TorrentError(why)

    video, extras = pick(folder)
    if video is None:
        raise TorrentError("בטורנט אין קובץ וידאו")
    keep = work / EXTRAS_DIR
    keep.mkdir(exist_ok=True)
    for item in extras:
        name = item.name
        if (keep / name).exists():
            name = f"{item.parent.name}-{name}"
        shutil.move(str(item), keep / name)
    final = work / f"source{video.suffix.lower()}"
    shutil.move(str(video), final)
    shutil.rmtree(folder, ignore_errors=True)
    saved = Path(target)
    if url.lower().startswith(PREFIX) and config.WORK_DIR in saved.parents:
        saved.unlink(missing_ok=True)   # רק העותק שהבוט שמר
    log.info("טורנט הורד: %s (%.2fGB) ועוד %d קבצים נלווים",
             final.name, final.stat().st_size / 1024 ** 3, len(extras))
    return final
