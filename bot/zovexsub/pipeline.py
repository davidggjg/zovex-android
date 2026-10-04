"""הצינור המלא: וידאו ⇒ אודיו ⇒ תמלול ⇒ חקר ⇒ עברית ⇒ SRT ⇒ (צריבה)."""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from . import config, hebrew, media, progress as prog, realign, srt
from .stt import transcribe

log = logging.getLogger(__name__)

Progress = Callable[[str], Awaitable[None]]


@dataclass
class Result:
    srt_path: Path
    duration: float
    cues: int
    language: str
    notes: str
    elapsed: float

    @property
    def burnable(self) -> bool:
        """צריבה מוצעת רק לסרטונים קצרים — כדי לא להעמיס את השרת."""
        return self.duration <= config.BURN_MAX_MINUTES * 60


async def run(source: Path, work: Path, *, progress: Progress) -> Result:
    """progress מקבל טקסט מוכן להצגה — כאן נבנים השלבים עם אחוזים וזמן משוער."""
    started = time.monotonic()
    work.mkdir(parents=True, exist_ok=True)

    if not await media.has_audio(source):
        raise RuntimeError("לקובץ הזה אין ערוץ אודיו — אין מה לתמלל.")

    duration = await media.duration_seconds(source)
    if duration > config.MAX_INPUT_MINUTES * 60:
        raise RuntimeError(
            f"הקובץ באורך {duration / 60:.0f} דקות, והמגבלה היא "
            f"{config.MAX_INPUT_MINUTES} דקות."
        )

    await progress(f"🎧 מחלץ אודיו · {duration / 60:.0f} דקות וידאו")
    audio = await media.extract_audio(source, work / "audio.flac")
    chunks = await media.split_audio(audio, work, duration)

    stage = prog.Stage(progress, "✍️ מתמלל")

    async def on_chunk(done: int, total: int) -> None:
        await stage.show(done / total, note=f"קטע {done}/{total}")

    transcript = await transcribe(chunks, on_chunk=on_chunk)
    await stage.finish()
    if not transcript.segments:
        raise RuntimeError("לא זוהה דיבור בקובץ.")
    log.info("זוהו %d סגמנטים, שפה: %s", len(transcript.segments), transcript.language)

    await progress("🔇 מזהה דיבור ושקט…")
    speech = await media.speech_spans(audio)

    stage = prog.Stage(progress, "🎯 מדייק תזמונים")

    async def on_listen(done: int, total: int) -> None:
        await stage.show(done / total, note=f"מקשיב שוב {done}/{total}")

    await realign.refine(transcript.segments, audio, work, speech, on_step=on_listen)

    stage = prog.Stage(progress, "🇮🇱 מתרגם")
    await stage.show(0.02, note=f"חוקר את התוכן · מקור {transcript.language}", force=True)

    async def on_translate(note: str, fraction: float) -> None:
        await stage.show(fraction, note=note)

    lines, notes = await hebrew.build_hebrew(transcript.segments, transcript.language,
                                             on_step=on_translate)
    await stage.finish()

    cues = srt.build_cues(transcript.segments, lines, speech=speech)
    if not cues:
        raise RuntimeError("התרגום חזר ריק.")
    srt_path = work / f"{source.stem}.he.srt"
    srt_path.write_text(srt.render(cues), encoding="utf-8")
    (work / "notes.md").write_text(notes, encoding="utf-8")

    return Result(
        srt_path=srt_path, duration=duration, cues=len(cues),
        language=transcript.language, notes=notes,
        elapsed=time.monotonic() - started,
    )


async def burn(source: Path, srt_path: Path, work: Path, on_progress=None) -> Path:
    """צריבה בפני עצמה — נקראת רק אחרי שהמשתמש אישר במפורש."""
    duration = await media.duration_seconds(source)
    if duration > config.BURN_MAX_MINUTES * 60:
        raise RuntimeError(
            f"צריבה מתבצעת רק עד {config.BURN_MAX_MINUTES} דקות "
            f"(הקובץ הזה {duration / 60:.0f} דקות)."
        )
    return await media.burn(source, srt_path, work / f"{source.stem}.he.mp4",
                            on_progress=on_progress)


def cleanup(work: Path) -> None:
    shutil.rmtree(work, ignore_errors=True)
