"""עבודה עם ffmpeg: אורך, חילוץ אודיו, חיתוך לחלקים, צריבה."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
from contextlib import asynccontextmanager
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
            f"הצריבה עברה את תקרת הזמן ({timeout / 60:.0f} דקות) ונעצרה. "
            f"להעלאת התקרה: BURN_TIMEOUT_FACTOR ב-.env"
        ) from None
    except asyncio.CancelledError:
        # בלי זה ffmpeg היה ממשיך לרוץ יתום אחרי ביטול העבודה
        proc.kill()
        await proc.wait()
        raise
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
        raise FFmpegError(
            f"הצריבה עברה את תקרת הזמן ({timeout / 60:.0f} דקות) ונעצרה. "
            f"להעלאת התקרה: BURN_TIMEOUT_FACTOR ב-.env"
        ) from None
    except asyncio.CancelledError:
        # בלי זה ffmpeg היה ממשיך לרוץ יתום אחרי ביטול העבודה
        proc.kill()
        await proc.wait()
        raise

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


def _escape(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _video_filters(srt: Path, credit: Path | None) -> str:
    filters = []
    if config.BURN_MAX_HEIGHT:
        # min() מבטיח שמקור נמוך מהתקרה נשאר כמו שהוא ולא מוגדל
        filters.append(f"scale=-2:'min({config.BURN_MAX_HEIGHT},ih)':flags=lanczos")
    filters.append(f"subtitles='{_escape(srt)}':force_style='{SUB_STYLE}'")
    if credit:
        filters.append(f"subtitles='{_escape(credit)}'")
    return ",".join(filters)


def _encoder_args(settings: dict, threads: int, duration: float) -> list[str]:
    codec = config.BURN_CODEC or settings["codec"]
    preset = config.BURN_PRESET or settings["preset"]
    crf = config.BURN_CRF or str(settings["crf"])
    pix_fmt = config.BURN_PIX_FMT or settings["pix_fmt"]
    tune = config.BURN_TUNE or settings["tune"]

    args = ["-c:v", codec, "-preset", preset, "-crf", str(crf), "-pix_fmt", pix_fmt]
    if tune:
        args += ["-tune", tune]
    if codec == "libx265":
        # hvc1 מאפשר ניגון בנגנים של אפל ובטלגרם; pools מגביל את הליבות
        args += ["-tag:v", "hvc1", "-x265-params", f"pools={threads}"]
    elif codec == "libx264":
        args += ["-x264-params", f"threads={threads}"]

    # CRF בלבד לא מבטיח גודל. תקרת bitrate עם חוצץ ("capped CRF") שומרת
    # על האיכות המשתנה ובכל זאת מבטיחה שהקובץ ייכנס במגבלת ההעלאה.
    cap = _bitrate_cap(duration) if config.UPLOAD_LIMIT_MB else 0
    if cap:
        args += ["-maxrate", f"{cap}k", "-bufsize", f"{cap * 2}k"]
        log.info("תקרת bitrate: %dkbps כדי להישאר מתחת ל-%dMB",
                 cap, config.UPLOAD_LIMIT_MB)
    return args


def _describe_profile(settings: dict, video: Path, duration: float) -> None:
    log.info("פרופיל צריבה: %s (%s %s CRF%s) למקור של %.0fMB באורך %.0f דקות",
             config.profile_name(settings),
             config.BURN_CODEC or settings["codec"],
             config.BURN_PRESET or settings["preset"],
             config.BURN_CRF or settings["crf"],
             video.stat().st_size / 1024 ** 2, duration / 60)


class CorePool:
    """מחלק את ליבות הצריבה בין העבודות שרצות על המכונה.

    סמפור לא מספיק כאן: הוא FIFO, וצריבה שנרשמה ראשונה מכניסה את כל
    הקטעים שלה לתור לפני שהשנייה בכלל מגיעה — כלומר השנייה ממתינה
    לראשונה במלואה במקום להתחלק איתה.

    כאן לכל עבודה יש מכסה שמחושבת מחדש לפי כמה עבודות רצות ברגע זה:
    עבודה לבדה מקבלת את כל המכונה, ושתיים מתחלקות בשווה. המכסה לא
    מבוזבזת — אם אף עבודה שממתינה לא מתחת למכסה שלה, מי שממתין יכול
    לקחת בכל זאת, כדי שלא יישאר מקום פנוי סתם.
    """

    def __init__(self, slots: int):
        self.slots = slots
        self.free = slots
        self.held: dict[int, int] = {}
        # ספירה ולא קבוצה: לעבודה אחת יש הרבה קטעים ממתינים, וכשאחד
        # מהם תופס מקום השאר עדיין ממתינים. קבוצה הייתה מוחקת את העבודה
        # מהרשימה ואז השנייה הייתה נראית כאילו אף אחד לא מחכה לה
        self.waiting: dict[int, int] = {}
        self.cond = asyncio.Condition()
        self._next = 0

    def share(self) -> int:
        return max(1, self.slots // max(1, len(self.held)))

    @asynccontextmanager
    async def job(self):
        """נרשם כעבודה, וכך משנה את המכסה של כל השאר."""
        async with self.cond:
            self._next += 1
            token = self._next
            self.held[token] = 0
            self.cond.notify_all()
        log.info("צריבה %d נכנסה: %d עבודות, מכסה %d קטעים (%d ליבות)",
                 token, len(self.held), self.share(),
                 self.share() * config.BURN_SEGMENT_THREADS)
        try:
            yield token
        finally:
            async with self.cond:
                self.held.pop(token, None)
                self.waiting.pop(token, None)
                self.cond.notify_all()

    @asynccontextmanager
    async def slot(self, token: int):
        """תופס מקום אחד, וממתין אם העבודה כבר מיצתה את המכסה שלה."""
        def ready() -> bool:
            if self.free <= 0 or token not in self.held:
                return self.free > 0
            limit = self.share()
            return (self.held[token] < limit
                    or not any(self.held.get(other, 0) < limit
                               for other, pending in self.waiting.items()
                               if pending and other != token))

        async with self.cond:
            self.waiting[token] = self.waiting.get(token, 0) + 1
            try:
                await self.cond.wait_for(ready)
            finally:
                self.waiting[token] = max(0, self.waiting.get(token, 1) - 1)
            self.free -= 1
            self.held[token] = self.held.get(token, 0) + 1
        try:
            yield
        finally:
            async with self.cond:
                self.free += 1
                if token in self.held:
                    self.held[token] -= 1
                self.cond.notify_all()


# בריכת הליבות של המכונה, משותפת לכל הצריבות. נוצרת בפעם הראשונה שצריך
# אותה, כדי שתהיה שייכת ללולאת האירועים הרצה
_pool: CorePool | None = None


def core_pool() -> CorePool:
    global _pool
    if _pool is None:
        count = config.burn_slots(os.cpu_count() or 2)
        _pool = CorePool(count)
        log.info("מקומות צריבה במכונה: %d (×%d חוטים = %d ליבות)",
                 count, config.BURN_SEGMENT_THREADS,
                 count * config.BURN_SEGMENT_THREADS)
    return _pool


async def burn(video: Path, srt: Path, dst: Path, on_progress=None) -> Path:
    """צריבה. במכונה עם הרבה ליבות מפוצלת לקטעים מקבילים."""
    duration = await duration_seconds(video)
    segments = config.burn_chunks(duration)

    if segments > 1 and duration >= config.BURN_PARALLEL_MIN_MINUTES * 60:
        try:
            return await _burn_parallel(video, srt, dst, duration, segments, on_progress)
        except Exception as exc:  # noqa: BLE001 — עדיף צריבה איטית מכשלון
            log.warning("הצריבה המקבילית נכשלה (%s), עוברים לצריבה רגילה", exc)

    return await _burn_single(video, srt, dst, duration, on_progress)


async def _burn_single(video: Path, srt: Path, dst: Path, duration: float,
                       on_progress=None) -> Path:
    marked = rtl_copy(srt)
    credit = credit_file(dst.parent)
    settings = config.profile_for(video.stat().st_size, duration)
    _describe_profile(settings, video, duration)
    threads = burn_threads()

    cmd = [
        "ffmpeg", "-nostdin", "-y", "-threads", str(threads),
        "-i", str(video), "-vf", _video_filters(marked, credit),
    ] + _encoder_args(settings, threads, duration)
    cmd += ["-c:a", "copy", "-movflags", "+faststart", str(dst)]

    limit = config.burn_timeout(duration)
    log.info("צריבה בתהליך אחד, %d חוטים, תקרת זמן %.0f דקות", threads, limit / 60)
    # גם תהליך יחיד נרשם כעבודה, כדי שלא יתחרה בצריבה שרצה לידו
    pool = core_pool()
    async with pool.job() as token, pool.slot(token):
        if on_progress:
            await _run_progress(cmd, duration, on_progress, timeout=limit)
        else:
            await _run(cmd, timeout=limit)

    log.info("הצריבה הסתיימה: %.0fMB", dst.stat().st_size / 1024 ** 2)
    return dst


async def _burn_parallel(video: Path, srt: Path, dst: Path, duration: float,
                         segments: int, on_progress=None) -> Path:
    """חותך את הווידאו לקטעים, צורב כל אחד בתהליך משלו, ומרכיב בחזרה.

    מסנן הכתוביות של ffmpeg רץ בחוט אחד, ולכן תהליך יחיד לא מצליח להעסיק
    מכונה עם הרבה ליבות — המקודד ממתין לפריימים. תהליך לכל קטע נותן
    צינור רינדור נפרד לכל אחד, וזה מה שמנצל את הליבות בפועל.

    האודיו אינו נוגע בקידוד: הקטעים נצרבים ללא קול, ובסוף מוזג האודיו
    המקורי כמו שהוא. כך אין סיכון להיסט קול בין הקטעים.
    """
    from . import srt as srt_tools

    work = dst.parent / "parallel"
    work.mkdir(parents=True, exist_ok=True)
    marked = rtl_copy(srt)
    credit = credit_file(work)
    settings = config.profile_for(video.stat().st_size, duration)
    _describe_profile(settings, video, duration)

    threads = config.BURN_SEGMENT_THREADS
    span = duration / segments
    limit = config.burn_timeout(span)
    pool = core_pool()
    log.info("צריבה מקבילית: %d קטעים של %.1f דקות, %d חוטים לקטע, "
             "עד %d קטעים בו-זמנית",
             segments, span / 60, threads, config.burn_slots(os.cpu_count() or 2))

    done = [0.0] * segments
    lock = asyncio.Lock()
    started = time.monotonic()

    async def one(index: int) -> Path:
        begin = index * span
        length = min(span, duration - begin)
        piece_srt = srt_tools.slice_file(marked, begin, begin + length,
                                         work / f"seg{index:02d}.srt")
        # הקרדיט מופיע רק בפתיחת הסרט, כלומר רק בקטע הראשון
        filters = _video_filters(piece_srt, credit if index == 0 else None)
        piece = work / f"seg{index:02d}.mp4"

        cmd = [
            "ffmpeg", "-nostdin", "-y",
            "-ss", f"{begin:.3f}", "-t", f"{length:.3f}",
            "-threads", str(threads), "-i", str(video),
            "-vf", filters,
        ] + _encoder_args(settings, threads, duration)
        cmd += ["-an", "-movflags", "+faststart", str(piece)]

        async def progress(fraction: float, speed: str) -> None:
            async with lock:
                done[index] = fraction * length
                if not on_progress:
                    return
                # הקצב שffmpeg מדווח הוא של תהליך בודד. בצריבה מקבילית
                # מעניין הקצב המצרפי, ולכן הוא נמדד מול שעון הקיר: כמה
                # שניות וידאו נצרבו בסך הכל חלקי הזמן שעבר באמת.
                elapsed = time.monotonic() - started
                rate = sum(done) / elapsed if elapsed > 1 else 0.0
                await on_progress(min(1.0, sum(done) / duration),
                                  f"{rate:.1f}x" if rate else speed)

        # ממתין למקום פנוי במכונה. זה מה שמחלק את הליבות בין צריבות
        # מקבילות: קטע שמחכה לא צורך כלום
        async with pool.slot(token):
            await _run_progress(cmd, length, progress, timeout=limit)
        log.info("קטע %d/%d הסתיים", index + 1, segments)
        return piece

    async with pool.job() as token:
        pieces = await asyncio.gather(*(one(i) for i in range(segments)))

    listing = work / "concat.txt"
    listing.write_text(
        "".join(f"file '{piece.name}'\n" for piece in pieces), encoding="utf-8"
    )
    silent = work / "joined.mp4"
    await _run([
        "ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0",
        "-i", str(listing), "-c", "copy", str(silent),
    ])

    # האודיו המקורי מוזג כמו שהוא, בלי קידוד מחדש
    await _run([
        "ffmpeg", "-nostdin", "-y", "-i", str(silent), "-i", str(video),
        "-map", "0:v:0", "-map", "1:a:0?", "-c", "copy",
        "-movflags", "+faststart", "-shortest", str(dst),
    ])

    await _verify(dst, duration)
    shutil.rmtree(work, ignore_errors=True)
    log.info("הצריבה המקבילית הסתיימה: %.0fMB", dst.stat().st_size / 1024 ** 2)
    return dst


async def _verify(result: Path, expected: float) -> None:
    """בלי אימות, הרכבה שבורה מגיעה למשתמש בשקט."""
    if not result.exists() or result.stat().st_size < 1024:
        raise FFmpegError("קובץ הפלט ריק")
    info = await probe(result)
    kinds = {stream.get("codec_type") for stream in info.get("streams", [])}
    if "video" not in kinds:
        raise FFmpegError("אין זרם וידאו בפלט")
    actual = float(info.get("format", {}).get("duration", 0) or 0)
    if abs(actual - expected) > max(2.0, expected * 0.01):
        raise FFmpegError(
            f"אורך הפלט {actual:.1f} שניות במקום {expected:.1f} — ההרכבה לא תקינה"
        )
    log.info("אימות ההרכבה עבר: %.1f שניות, זרמים %s", actual, ", ".join(sorted(kinds)))


def _bitrate_cap(duration: float) -> int:
    """כמה kbps מותר לווידאו כדי שהקובץ כולו ייכנס במגבלת ההעלאה."""
    if duration <= 0:
        return 0
    budget_bits = config.UPLOAD_LIMIT_MB * 1024 ** 2 * 8 * 0.90  # שוליים לאודיו ולמכולה
    return max(300, int(budget_bits / duration / 1000))
