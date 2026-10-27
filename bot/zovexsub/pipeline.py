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
from .stt import recover_gaps, transcribe

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


async def run(source: Path, work: Path, *, progress: Progress,
              card: "prog.Card | None" = None, track: int = 0) -> Result:
    """progress מקבל טקסט מוכן להצגה — כאן נבנים השלבים עם אחוזים וזמן משוער.

    card אופציונלי: כשהוא קיים כל שלב שמסתיים נשאר כשורה בהיסטוריה
    במקום להידרס על ידי הבא אחריו
    """
    def make(title: str, **kwargs) -> prog.Stage:
        # בלי כרטיס חוזרים לשלב רגיל שכותב ישירות. כאן הייתה רקורסיה
        # אינסופית: ההחלפה שהכניסה את make פגעה גם בגוף שלה עצמה והפכה
        # את הנפילה-לאחור לקריאה עצמית. זה לא התפוצץ עד שהגיע מסלול
        # שאינו מעביר כרטיס
        if card is not None:
            return card.stage(title, **kwargs)
        return prog.Stage(progress, title, **kwargs)

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
    audio = await media.extract_audio(source, work / "audio.flac", track)

    stage = make("✍️ מתמלל")
    stage.pulse()

    async def on_chunk(done: int, total: int, note: str = "") -> None:
        # note אופציונלי: ג'ימיני מדווח גם מה קורה בתוך חלק שעוד לא
        # הסתיים, ו-Groq שולח שניים בלבד
        await stage.show(done / max(1, total),
                         note=note or f"{done}/{total} קטעים")

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
        stage = make("📐 מיישר תזמונים")
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

    # הצלת דיבור שהתמלול פספס. נמדד בשטח: 19 עד 45 שניות בכל פרק
    # נשמעו ל-VAD וחזרו ריקות מהתמלול, וזה נרשם ללוג בלבד. חור אינו
    # נשאר חור — הכתוביות סביבו נמתחות לכסות אותו, וכתובית שנמתחה על
    # פני עשר שניות מופיעה בזמן הלא נכון. לכן מילים חסרות נראות
    # למשתמש כבעיית תזמון, וכאן הן מטופלות במקור
    if config.RECOVER_GAPS and speech:
        stage = make("🔁 משלים דיבור חסר")
        stage.pulse()

        async def on_gap(done: int, total: int) -> None:
            await stage.show(done / max(1, total), note=f"{done}/{total} קטעים")

        try:
            await recover_gaps(transcript.segments, speech, audio, work,
                               on_step=on_gap)
        except Exception as exc:  # noqa: BLE001 — השלמה אינה תנאי
            log.warning("השלמת הדיבור החסר נכשלה (%s) — ממשיכים בלעדיה", exc)
        finally:
            stage.stop()
        await stage.finish()

    # ההקשבה החוזרת מתמללת עד 60 קליפים מחדש, אחד-אחד בטור, כל אחד עם
    # חיתוך ffmpeg וקריאת Groq — דקות ארוכות. היא נבנתה כדי לתקן בדיוק
    # את מה שהיישור הכפוי מתקן, רק פחות מדויק ובמחיר עצום, ולכן כשהיישור
    # זמין היא מיותרת לחלוטין
    if native_times or align.available():
        log.info("מדלגים על ההקשבה החוזרת — התזמונים כבר מדויקים")
    else:
        stage = make("🎯 מדייק תזמונים")
        stage.pulse()

        async def on_listen(done: int, total: int) -> None:
            await stage.show(done / total, note=f"מקשיב שוב {done}/{total}")

        try:
            await realign.refine(transcript.segments, audio, work, speech,
                                 on_step=on_listen)
        finally:
            stage.stop()

    stage = make("🇮🇱 מתרגם")
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
    # חיתוכי צילום: אריתמטיקה בלבד, בלי שום קריאת מודל. כתובית שחוצה
    # חיתוך נקראת פעמיים על ידי הצופה, וזה החוק שמבדיל קובץ מקצועי
    # שתי שורות הן תקרה בכל תקן מקצועי. כתובית שאינה נכנסת בהן מפוצלת
    # לשתי כתוביות — ולא מקבלת שורה שלישית, שמכריחה את העין לשלוש
    # תנועות סריקה בזמן שהפריים ממשיך לזוז
    fps = await media.video_fps(source) or 24.0
    split = srt.split_overlong(cues, fps)
    if split:
        log.info("פוצלו %d כתוביות שלא נכנסו בשתי שורות", split)

    if config.SRT_SNAP_CUTS:
        await progress("🎬 מרחיק כתוביות מחיתוכי צילום…")
        cuts = await media.scene_cuts(source, config.SCENE_THRESHOLD)
        if cuts:
            moved = srt.snap_to_cuts(cues, cuts, fps)
            log.info("הוזזו %d כתוביות מחיתוכי צילום (מתוך %d, %.0f fps)",
                     moved, len(cues), fps)
            # אחרון בשרשרת, כי ההצמדה לחיתוכים פותחת מרווחים חדשים
            closed = srt.close_gaps(cues, fps)
            log.info("נסגרו %d מרווחי הבהוב", closed)

    # השער האחרון לפני הכתיבה: כל מה שרץ עד כאן שינה טקסט וזמנים,
    # ואיש לא בדק אותם שוב. ראו srt.finalize
    repaired = srt.finalize(cues, fps)
    if repaired:
        log.info("מעבר אחרון תיקן: %s",
                 " · ".join(f"{name} {count}"
                            for name, count in repaired.items()))

    srt_path = work / f"{source.stem}.he.srt"
    srt_path.write_text(srt.render(cues), encoding="utf-8")
    (work / "notes.md").write_text(notes, encoding="utf-8")

    return Result(
        srt_path=srt_path, duration=duration, cues=len(cues),
        language=transcript.language, notes=notes,
        elapsed=time.monotonic() - started,
    )


async def burn(source: Path, srt_path: Path, work: Path, on_progress=None,
               style: "media.Style | None" = None, profile: str = "") -> Path:
    """צריבה בפני עצמה — נקראת רק אחרי שהמשתמש אישר במפורש."""
    duration = await media.duration_seconds(source)
    if duration > config.BURN_MAX_MINUTES * 60:
        raise RuntimeError(
            f"צריבה מתבצעת רק עד {config.BURN_MAX_MINUTES} דקות "
            f"(הקובץ הזה {duration / 60:.0f} דקות)."
        )
    return await media.burn(source, srt_path, work / f"{source.stem}.he.mp4",
                            on_progress=on_progress, style=style,
                            profile=profile)


def cleanup(work: Path) -> None:
    shutil.rmtree(work, ignore_errors=True)
