"""הצינור המלא: וידאו ⇒ אודיו ⇒ תמלול ⇒ חקר ⇒ עברית ⇒ SRT ⇒ (צריבה)."""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from . import config, hebrew, media, srt
from .stt import transcribe

log = logging.getLogger(__name__)

Progress = Callable[[str], Awaitable[None]]


@dataclass
class Result:
    srt_path: Path
    burned_path: Path | None
    duration: float
    cues: int
    language: str
    notes: str
    elapsed: float
    burn_skipped: str | None = None


async def run(source: Path, work: Path, *, burn: bool, progress: Progress) -> Result:
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

    await progress(f"🎧 מחלץ אודיו ({duration / 60:.1f} דקות)…")
    audio = await media.extract_audio(source, work / "audio.flac")
    chunks = await media.split_audio(audio, work, duration)

    await progress(f"✍️ מתמלל ({len(chunks)} קטעים)…")
    transcript = await transcribe(chunks)
    if not transcript.segments:
        raise RuntimeError("לא זוהה דיבור בקובץ.")
    log.info("זוהו %d סגמנטים, שפה: %s", len(transcript.segments), transcript.language)

    await progress(f"🔎 חוקר את התוכן (שפת מקור: {transcript.language})…")
    lines, notes = await hebrew.build_hebrew(transcript.segments, transcript.language)

    cues = srt.build_cues(transcript.segments, lines)
    if not cues:
        raise RuntimeError("התרגום חזר ריק.")
    srt_path = work / f"{source.stem}.he.srt"
    srt_path.write_text(srt.render(cues), encoding="utf-8")
    (work / "notes.md").write_text(notes, encoding="utf-8")

    burned: Path | None = None
    skipped: str | None = None
    if burn:
        if duration > config.BURN_MAX_MINUTES * 60:
            skipped = (
                f"צריבה מתבצעת רק עד {config.BURN_MAX_MINUTES} דקות "
                f"(הקובץ הזה {duration / 60:.0f} דקות) — שולח SRT בלבד."
            )
        else:
            await progress("🔥 צורב כתוביות…")
            burned = await media.burn(source, srt_path, work / f"{source.stem}.he.mp4")

    return Result(
        srt_path=srt_path, burned_path=burned, duration=duration, cues=len(cues),
        language=transcript.language, notes=notes,
        elapsed=time.monotonic() - started, burn_skipped=skipped,
    )


def cleanup(work: Path) -> None:
    shutil.rmtree(work, ignore_errors=True)
