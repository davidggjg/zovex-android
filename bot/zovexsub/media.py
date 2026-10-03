"""עבודה עם ffmpeg: אורך, חילוץ אודיו, חיתוך לחלקים, צריבה."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import config

log = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    pass


def _nice_prefix() -> list[str]:
    """מריץ ffmpeg בעדיפות נמוכה כדי לא להעמיס שרת תפוס."""
    prefix: list[str] = []
    if config.NICE and shutil.which("nice"):
        prefix += ["nice", "-n", str(config.NICE)]
    if shutil.which("ionice"):
        prefix += ["ionice", "-c", "3"]
    return prefix


async def _run(cmd: list[str], *, nice: bool = True) -> str:
    full = (_nice_prefix() if nice else []) + cmd
    proc = await asyncio.create_subprocess_exec(
        *full, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        tail = err.decode("utf-8", "replace").strip().splitlines()[-12:]
        raise FFmpegError("\n".join(tail) or f"exit {proc.returncode}")
    return out.decode("utf-8", "replace")


async def probe(path: Path) -> dict:
    raw = await _run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        nice=False,
    )
    return json.loads(raw)


async def duration_seconds(path: Path) -> float:
    info = await probe(path)
    try:
        return float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        for stream in info.get("streams", []):
            if stream.get("duration"):
                return float(stream["duration"])
    raise FFmpegError("לא הצלחתי לקרוא את אורך הקובץ")


async def has_audio(path: Path) -> bool:
    info = await probe(path)
    return any(s.get("codec_type") == "audio" for s in info.get("streams", []))


async def extract_audio(src: Path, dst: Path) -> Path:
    """FLAC 16kHz מונו — מה ש-Whisper אוהב, וגם הקטן ביותר ללא איבוד דיוק."""
    await _run([
        "ffmpeg", "-nostdin", "-y", "-threads", str(config.FFMPEG_THREADS),
        "-i", str(src), "-vn", "-map", "0:a:0",
        "-ac", "1", "-ar", "16000", "-c:a", "flac", "-compression_level", "8",
        str(dst),
    ])
    return dst


@dataclass
class Chunk:
    path: Path
    offset: float  # שנייה שבה החלק מתחיל בתוך המקור


async def split_audio(audio: Path, out_dir: Path, total: float) -> list[Chunk]:
    """מחלק אודיו לחלקים שנכנסים במגבלת הגודל של ה-API.

    החלוקה היא לפי זמן, וה-offset נשמר כדי שחותמות הזמן יחזרו למקום הנכון.
    """
    size = audio.stat().st_size
    if size <= config.STT_CHUNK_BYTES and total <= config.STT_CHUNK_SECONDS:
        return [Chunk(audio, 0.0)]

    # אורך חלק שמבטיח גם גודל וגם תקרת זמן
    by_size = total * (config.STT_CHUNK_BYTES / size) * 0.9
    chunk_len = max(60.0, min(float(config.STT_CHUNK_SECONDS), by_size))

    chunks: list[Chunk] = []
    start = 0.0
    idx = 0
    while start < total - 0.25:
        dst = out_dir / f"part{idx:03d}.flac"
        await _run([
            "ffmpeg", "-nostdin", "-y", "-threads", str(config.FFMPEG_THREADS),
            "-ss", f"{start:.3f}", "-t", f"{chunk_len:.3f}", "-i", str(audio),
            "-ac", "1", "-ar", "16000", "-c:a", "flac", "-compression_level", "8",
            str(dst),
        ])
        chunks.append(Chunk(dst, start))
        start += chunk_len
        idx += 1
    log.info("האודיו חולק ל-%d חלקים של ~%.0f שניות", len(chunks), chunk_len)
    return chunks


SUB_STYLE = (
    "FontName=Noto Sans Hebrew,FontSize=20,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
    "Alignment=2,MarginV=28"
)


RLM = "\u200f"  # Right-to-Left Mark


def rtl_copy(srt: Path) -> Path:
    """עותק לצריבה עם סימון כיווניות בתחילת כל שורת טקסט.

    בלי זה libass מחליט על כיוון השורה לפי התו הראשון, ושורה שמתחילה
    בספרה או באות לטינית גוררת את סימני הפיסוק לצד הלא נכון.
    הקובץ שנשלח למשתמש נשאר נקי — הסימון רק בעותק הזה.
    """
    out = []
    for line in srt.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        is_meta = (not stripped) or stripped.isdigit() or "-->" in stripped
        if is_meta:
            out.append(line)
        else:
            out.append(RLM + line.lstrip(RLM))
    dst = srt.with_name(srt.stem + ".rtl.srt")
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    return dst


async def burn(video: Path, srt: Path, dst: Path) -> Path:
    """צריבה 'חלשה ומהירה' — preset מהיר, CRF גבוה, thread אחד, הקטנת רזולוציה."""
    srt = rtl_copy(srt)
    escaped = str(srt).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    vf = (
        f"scale=-2:'min({config.BURN_MAX_HEIGHT},ih)':flags=fast_bilinear,"
        f"subtitles='{escaped}':force_style='{SUB_STYLE}'"
    )
    await _run([
        "ffmpeg", "-nostdin", "-y", "-threads", str(config.FFMPEG_THREADS),
        "-i", str(video), "-vf", vf,
        "-c:v", "libx264", "-preset", config.BURN_PRESET, "-crf", str(config.BURN_CRF),
        "-x264-params", f"threads={config.FFMPEG_THREADS}",
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
        str(dst),
    ])
    return dst
