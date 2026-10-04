"""עבודה עם ffmpeg: אורך, חילוץ אודיו, חיתוך לחלקים, צריבה."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
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


async def _run(cmd: list[str], *, nice: bool = True,
               timeout: float | None = None) -> str:
    full = (_nice_prefix() if nice else []) + cmd
    proc = await asyncio.create_subprocess_exec(
        *full, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise FFmpegError(
            f"ffmpeg עבר את תקרת הזמן ({timeout:.0f} שניות) ונעצר"
        ) from None
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


async def cut_audio(audio: Path, start: float, end: float, dst: Path) -> Path:
    """חותך קטע אודיו לבדיקה חוזרת."""
    await _run([
        "ffmpeg", "-nostdin", "-y", "-threads", str(config.FFMPEG_THREADS),
        "-ss", f"{max(0.0, start):.3f}", "-t", f"{max(0.2, end - start):.3f}",
        "-i", str(audio), "-ac", "1", "-ar", "16000", "-c:a", "flac", str(dst),
    ])
    return dst


async def _run_progress(cmd: list[str], total: float, on_progress, *,
                        timeout: float | None = None) -> None:
    """מריץ ffmpeg וקורא את ההתקדמות שלו תוך כדי ריצה."""
    full = _nice_prefix() + cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    proc = await asyncio.create_subprocess_exec(
        *full, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    async def pump() -> None:
        speed = ""
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("speed="):
                speed = line.split("=", 1)[1].strip()
            elif line.startswith("out_time_us=") and total > 0:
                try:
                    done = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                await on_progress(min(1.0, done / total), speed)

    try:
        await asyncio.wait_for(asyncio.gather(pump(), proc.wait()), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise FFmpegError(f"ffmpeg עבר את תקרת הזמן ({timeout:.0f} שניות) ונעצר") from None

    if proc.returncode != 0:
        err = (await proc.stderr.read()).decode("utf-8", "replace") if proc.stderr else ""
        raise FFmpegError("\n".join(err.strip().splitlines()[-12:]) or "ffmpeg נכשל")


@dataclass
class Chunk:
    path: Path
    offset: float  # שנייה שבה החלק מתחיל בתוך המקור


async def split_audio(audio: Path, out_dir: Path, total: float,
                      workers: int = 1) -> list[Chunk]:
    """מחלק אודיו לחלקים שנכנסים במגבלת הגודל של ה-API.

    החלוקה היא לפי זמן, וה-offset נשמר כדי שחותמות הזמן יחזרו למקום הנכון.
    כשיש הרבה מפתחות שווה לחתוך דק יותר: כל חלק רץ על מפתח אחר, וכך
    כולם עובדים בו-זמנית במקום שחלקם ימתינו בתור.
    """
    size = audio.stat().st_size
    if size <= config.STT_CHUNK_BYTES and total <= config.STT_CHUNK_SECONDS and workers <= 1:
        return [Chunk(audio, 0.0)]

    # אורך חלק שמבטיח גם גודל וגם תקרת זמן
    by_size = total * (config.STT_CHUNK_BYTES / size) * 0.9
    chunk_len = max(60.0, min(float(config.STT_CHUNK_SECONDS), by_size))

    # להעסיק את כל המפתחות: חלק לכל אחד, אבל לא קצר מהמינימום
    if workers > 1:
        even = total / workers
        chunk_len = min(chunk_len, max(float(config.STT_CHUNK_MIN_SECONDS), even))

    if size <= config.STT_CHUNK_BYTES and total <= chunk_len:
        return [Chunk(audio, 0.0)]

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


async def mean_volume(audio: Path) -> float:
    """עוצמת הקול הממוצעת בדציבלים — בסיס לסף שמסתגל לתוכן."""
    proc = await asyncio.create_subprocess_exec(
        *(_nice_prefix() + ["ffmpeg", "-nostdin", "-i", str(audio),
                            "-af", "volumedetect", "-f", "null", "-"]),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    match = re.search(r"mean_volume: *(-?[\d.]+) dB", err.decode("utf-8", "replace"))
    return float(match.group(1)) if match else -30.0


# יחס הדיבור שאנחנו מצפים לו בתוכן דיאלוגי. סף שמוצא הרבה יותר מזה
# מחשיב מוזיקת רקע כדיבור; סף שמוצא הרבה פחות חותך תחילת מילים.
TARGET_SPEECH_RATIO = 0.60


async def speech_spans(audio: Path, min_silence: float = 0.18) -> list[tuple[float, float]]:
    """מאתר את הקטעים שבהם באמת מדברים.

    סף קבוע לא עובד: בתוכן עם מוזיקת רקע שום דבר לא יורד מתחת לסף נמוך,
    והכול מסווג כדיבור. לכן נבדקים כמה ספים סביב עוצמת הקול הממוצעת,
    ונבחר זה שמייצר יחס דיבור קרוב למצופה — לא הראשון שמחזיר משהו.
    """
    average = await mean_volume(audio)
    total = await duration_seconds(audio)
    if total <= 0:
        return []

    best: tuple[float, float, list] | None = None
    for offset in (-9.0, -6.0, -3.0, 0.0, 3.0, 6.0):
        threshold = max(-50.0, min(-12.0, average - offset))
        spans = await _detect(audio, threshold, min_silence, total)
        ratio = sum(b - a for a, b in spans) / total
        log.info("סף %.1fdB: %d קטעים, %.0f%% דיבור", threshold, len(spans), ratio * 100)
        if not spans or not 0.25 <= ratio <= 0.92:
            continue
        distance = abs(ratio - TARGET_SPEECH_RATIO)
        if best is None or distance < best[0]:
            best = (distance, threshold, spans)

    if best is None:
        log.info("אף סף לא הפריד בין דיבור לרקע — מדלגים על ההצמדה")
        return []

    _, threshold, spans = best
    log.info("נבחר סף %.1fdB עם %d קטעי דיבור", threshold, len(spans))
    return spans


async def _detect(audio: Path, threshold: float, min_silence: float,
                  total: float) -> list[tuple[float, float]]:
    cmd = ["ffmpeg", "-nostdin", "-i", str(audio), "-af",
           f"highpass=f=180,lowpass=f=3600,"
           f"silencedetect=noise={threshold}dB:d={min_silence}", "-f", "null", "-"]
    proc = await asyncio.create_subprocess_exec(
        *(_nice_prefix() + cmd),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    text = err.decode("utf-8", "replace")

    silences: list[tuple[float, float]] = []
    start: float | None = None
    for match in re.finditer(r"silence_(start|end): *(-?[\d.]+)", text):
        kind, value = match.group(1), float(match.group(2))
        if kind == "start":
            start = value
        elif start is not None:
            silences.append((start, value))
            start = None

    if start is not None:
        silences.append((start, total))

    spans, cursor = [], 0.0
    for begin, finish in silences:
        if begin - cursor > 0.05:
            spans.append((cursor, begin))
        cursor = max(cursor, finish)
    if total - cursor > 0.05:
        spans.append((cursor, total))
    return spans


CREDIT_ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: credit,Noto Sans Hebrew,{size},&H00FFFFFF,&H00000000,&H64000000,-1,0,1,2,1,5,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.20,{end},credit,,0,0,0,,{{\\fad(400,600)}}{text}
"""


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}.{int(seconds % 1 * 100):02d}"


def credit_file(work: Path) -> Path | None:
    """קרדיט פתיחה כקובץ ASS נפרד.

    נכתב כ-ASS ולא כטקסט על הווידאו כי libass מטפל נכון בכיווניות של
    העברית, בעוד ש-drawtext היה מציג את האותיות הפוכות.
    """
    if not config.CREDIT_TEXT.strip():
        return None
    lines = [part.strip() for part in config.CREDIT_TEXT.split("|") if part.strip()]
    if not lines:
        return None

    body = "\\N".join(RLE + line + PDF for line in lines)
    dst = work / "credit.ass"
    dst.write_text(
        CREDIT_ASS.format(size=config.CREDIT_SIZE,
                          end=_ass_time(config.CREDIT_SECONDS), text=body),
        encoding="utf-8",
    )
    return dst


SUB_STYLE = (
    "FontName=Noto Sans Hebrew,FontSize=20,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
    "Alignment=2,MarginV=28"
)


def burn_threads() -> int:
    """כמה ליבות לתת לצריבה עכשיו, לפי העומס בפועל.

    השרת מריץ דברים נוספים. בשעה שקטה אין סיבה להשאיר ליבות בטלות,
    ובשעת עומס אין סיבה להילחם על מעבד. nice ו-ionice ממשיכים לדאוג
    שגם המספר שנבחר כאן נדחק מיד כשתהליך אחר צריך את המעבד.
    """
    total = os.cpu_count() or 2
    setting = str(config.BURN_THREADS)
    if setting.isdigit():
        return max(1, min(int(setting), total))

    try:
        load = os.getloadavg()[0]
    except (OSError, AttributeError):
        load = 0.0

    free = total - load - config.RESERVE_CORES
    threads = int(max(1, min(total, round(free))))
    if config.BURN_THREADS_MAX:
        threads = min(threads, config.BURN_THREADS_MAX)
    log.info("עומס נוכחי %.1f מתוך %d ליבות — הצריבה תקבל %d",
             load, total, threads)
    return threads


RLE = "\u202b"  # Right-to-Left Embedding — פותח קטע שכיוונו מימין לשמאל
PDF = "\u202c"  # Pop Directional Formatting — סוגר אותו
_MARKS = "\u200e\u200f\u202a\u202b\u202c"


def rtl_copy(srt: Path) -> Path:
    """עותק לצריבה שבו כל שורת טקסט עטופה בהטבעה דו-כיוונית.

    libass קובע את כיוון השורה לפי התו הראשון שלה. שורה שמתחילה בספרה,
    באות לטינית או בסימן פיסוק נקראת כאילו היא משמאל לימין, והפיסוק
    הסופי קופץ לצד הלא נכון. העטיפה הזו היא הפתרון המקובל לעברית,
    ערבית ופרסית — היא קובעת את הכיוון במפורש במקום לנחש אותו.

    הקובץ שנשלח למשתמש נשאר נקי — העטיפה רק בעותק הזה.
    """
    out = []
    for line in srt.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        is_meta = (not stripped) or stripped.isdigit() or "-->" in stripped
        if is_meta:
            out.append(line)
        else:
            out.append(RLE + line.strip(_MARKS) + PDF)
    dst = srt.with_name(srt.stem + ".rtl.srt")
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    return dst


async def burn(video: Path, srt: Path, dst: Path, on_progress=None) -> Path:
    """צריבה לפי פרופיל האיכות, עם תקרת bitrate שמבטיחה שהקובץ ניתן להעלאה."""
    srt = rtl_copy(srt)
    duration = await duration_seconds(video)
    escaped = str(srt).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    filters = []
    if config.BURN_MAX_HEIGHT:
        # min() מבטיח שמקור נמוך מהתקרה נשאר כמו שהוא ולא מוגדל
        filters.append(f"scale=-2:'min({config.BURN_MAX_HEIGHT},ih)':flags=lanczos")
    filters.append(f"subtitles='{escaped}':force_style='{SUB_STYLE}'")

    credit = credit_file(dst.parent)
    if credit:
        credit_path = str(credit).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
        filters.append(f"subtitles='{credit_path}'")
    vf = ",".join(filters)
    settings = config.profile_for(video.stat().st_size, duration)
    codec = config.BURN_CODEC or settings["codec"]
    preset = config.BURN_PRESET or settings["preset"]
    crf = config.BURN_CRF or str(settings["crf"])
    pix_fmt = config.BURN_PIX_FMT or settings["pix_fmt"]
    tune = config.BURN_TUNE or settings["tune"]
    log.info("פרופיל צריבה: %s (%s %s CRF%s) למקור של %.0fMB באורך %.0f דקות",
             config.profile_name(settings), codec, preset, crf,
             video.stat().st_size / 1024 ** 2, duration / 60)

    threads = burn_threads()
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-threads", str(threads),
        "-i", str(video), "-vf", vf,
        "-c:v", codec,
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", pix_fmt,
    ]
    if tune:
        cmd += ["-tune", tune]
    if codec == "libx265":
        # hvc1 מאפשר ניגון בנגנים של אפל ובטלגרם; pools מגביל את הליבות
        cmd += ["-tag:v", "hvc1", "-x265-params", f"pools={threads}"]
    elif codec == "libx264":
        cmd += ["-x264-params", f"threads={threads}"]

    # CRF בלבד לא מבטיח גודל. תקרת bitrate עם חוצץ ("capped CRF") שומרת
    # על האיכות המשתנה ובכל זאת מבטיחה שהקובץ ייכנס במגבלת ההעלאה.
    cap = _bitrate_cap(duration) if config.UPLOAD_LIMIT_MB else 0
    if cap:
        cmd += ["-maxrate", f"{cap}k", "-bufsize", f"{cap * 2}k"]
        log.info("תקרת bitrate: %dkbps כדי להישאר מתחת ל-%dMB",
                 cap, config.UPLOAD_LIMIT_MB)

    cmd += ["-c:a", "copy", "-movflags", "+faststart", str(dst)]
    if on_progress:
        await _run_progress(cmd, duration, on_progress, timeout=config.BURN_TIMEOUT)
    else:
        await _run(cmd, timeout=config.BURN_TIMEOUT)

    size_mb = dst.stat().st_size / 1024 ** 2
    log.info("הצריבה הסתיימה: %.0fMB", size_mb)
    return dst


def _bitrate_cap(duration: float) -> int:
    """כמה kbps מותר לווידאו כדי שהקובץ כולו ייכנס במגבלת ההעלאה."""
    if duration <= 0:
        return 0
    budget_bits = config.UPLOAD_LIMIT_MB * 1024 ** 2 * 8 * 0.90  # שוליים לאודיו ולמכולה
    return max(300, int(budget_bits / duration / 1000))
