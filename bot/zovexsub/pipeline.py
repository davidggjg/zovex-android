"""הצינור המלא: וידאו ⇒ אודיו ⇒ תמלול ⇒ חקר ⇒ עברית ⇒ SRT ⇒ (צריבה)."""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from . import (align, config, gemini_stt, hebrew, media,
               progress as prog, realign, srt, vad)
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

    stage = prog.Stage(progress, "✍️ מתמלל")
    stage.pulse()

    async def on_chunk(done: int, total: int) -> None:
        await stage.show(done / total, note=f"{done}/{total} קטעים")

    # gemini-3.5-transcribe הוא מודל ASR ייעודי: הוא מחזיר תזמוני מילים
    # מדויקים במקור, ולכן התזמונים שלו לא צריכים יישור בדיעבד. הוא גם
    # מחזיר מי אמר כל מילה, וזה מה שהופך את מגדר הפנייה מניחוש לעובדה
    transcript = None
    native_times = False
    try:
        transcript = await gemini_stt.transcribe(audio, on_step=on_chunk)
        native_times = transcript is not None
    except Exception as exc:  # noqa: BLE001 — נופלים ל-Groq
        log.warning("תמלול ג'ימיני נכשל (%s), עוברים ל-Groq", exc)

    if transcript is None:
        workers = config.parallel(config.STT_PARALLEL, config.GROQ_API_KEYS)
        chunks = await media.split_audio(audio, work, duration, workers=workers)
        try:
            transcript = await transcribe(chunks, on_chunk=on_chunk, work=work)
        finally:
            stage.stop()
    stage.stop()
    await stage.finish()
    if not transcript.segments:
        raise RuntimeError("לא זוהה דיבור בקובץ.")
    log.info("זוהו %d סגמנטים, שפה: %s", len(transcript.segments), transcript.language)

    # יישור כפוי קודם לכל השאר: הוא מתקן את התזמונים עצמם, ולא רק מזיז
    # כתוביות שנחתו על שקט. אחריו ההצמדה ל-VAD נוגעת רק בשאריות
    if native_times:
        log.info("התזמונים הגיעו מהמודל עצמו — אין צורך ביישור")
    elif align.available():
        stage = prog.Stage(progress, "📐 מיישר תזמונים")
        stage.pulse()

        async def on_align(done: int, total: int) -> None:
            await stage.show(done / total, note=f"{done}/{total} חלונות")

        try:
            await align.refine(transcript.segments, audio, on_step=on_align)
        finally:
            stage.stop()
        await stage.finish()

    await progress("🔇 מזהה דיבור ושקט…")
    # VAD אמיתי קודם; אם הוא לא זמין נופלים לזיהוי לפי עוצמת קול
    speech = await vad.speech_spans(audio)
    if speech is None:
        speech = await media.speech_spans(audio)

    # ההקשבה החוזרת מתמללת עד 60 קליפים מחדש, אחד-אחד בטור, כל אחד עם
    # חיתוך ffmpeg וקריאת Groq — דקות ארוכות. היא נבנתה כדי לתקן בדיוק
    # את מה שהיישור הכפוי מתקן, רק פחות מדויק ובמחיר עצום, ולכן כשהיישור
    # זמין היא מיותרת לחלוטין
    if native_times or align.available():
        log.info("מדלגים על ההקשבה החוזרת — התזמונים כבר מדויקים")
    else:
        stage = prog.Stage(progress, "🎯 מדייק תזמונים")
        stage.pulse()

        async def on_listen(done: int, total: int) -> None:
            await stage.show(done / total, note=f"מקשיב שוב {done}/{total}")

        try:
            await realign.refine(transcript.segments, audio, work, speech,
                                 on_step=on_listen)
        finally:
            stage.stop()

    stage = prog.Stage(progress, "🇮🇱 מתרגם")
    await stage.show(0.04, note=f"חוקר את התוכן · מקור {transcript.language}",
                     force=True)

    stage.pulse()

    async def on_translate(note: str, fraction: float) -> None:
        await stage.show(fraction, note=note)

    try:
        lines, notes = await hebrew.build_hebrew(transcript.segments,
                                                 transcript.language,
                                                 on_step=on_translate)
    finally:
        stage.stop()
    await stage.finish()

    cues = srt.build_cues(transcript.segments, lines, speech=speech,
                          accurate=native_times or align.available())
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


async def burn(source: Path, srt_path: Path, work: Path, on_progress=None,
               size: str = "") -> Path:
    """צריבה בפני עצמה — נקראת רק אחרי שהמשתמש אישר במפורש."""
    duration = await media.duration_seconds(source)
    if duration > config.BURN_MAX_MINUTES * 60:
        raise RuntimeError(
            f"צריבה מתבצעת רק עד {config.BURN_MAX_MINUTES} דקות "
            f"(הקובץ הזה {duration / 60:.0f} דקות)."
        )
    return await media.burn(source, srt_path, work / f"{source.stem}.he.mp4",
                            on_progress=on_progress, size=size)


def cleanup(work: Path) -> None:
    shutil.rmtree(work, ignore_errors=True)
