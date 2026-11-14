"""הצינור המלא: וידאו ⇒ אודיו ⇒ תמלול ⇒ חקר ⇒ עברית ⇒ SRT ⇒ (צריבה)."""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from . import (align, config, gemini_stt, hebrew, idiom, media,
               memory, voice, progress as prog, realign, srt, vad)
from .stt import (Segment, drop_nonspeech, recover_gaps,
                  title_hint as stt_title_hint, transcribe)

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
            # הרמז נשלח לכל קטע ולא רק לראשון: prompt מכוון לבקשה
            # אחת, ולכן קטע שני והלאה תמלל את אותם שמות מאפס
            hint = stt_title_hint(source)
            if hint:
                log.info("רמז לתמלול: %s", hint)
            transcript = await transcribe(chunks, hint=hint or None,
                                          on_chunk=on_chunk, work=work)
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

    # הזיות על שקט: המודל אומן על קורפוס כתוביות, ולכן בקטע שקט הוא
    # פולט קרדיט של מתרגם או "תודה שצפיתם". נמדד אצל המשתמש —
    # "Undertexter av Nicolai Winther" באמצע סרט יפני.
    #
    # הסינון הישן רץ רק במסלול Groq, ואילו המסלול הראשי הוא ג'מיני:
    # הוא גם אינו מחזיר no_speech_prob, ולכן היה חשוף לגמרי. בדיקה
    # מול ה-VAD עובדת לשניהם, ואינה תלויה במה שהספק מדווח
    if speech:
        faked = drop_nonspeech(transcript.segments, speech)
        if faked:
            log.warning("נמחקו %d שורות שנאמרו היכן שלא נשמע דיבור", faked)

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
        lines, notes = await hebrew.build_hebrew(
            transcript.segments, transcript.language,
            on_step=on_translate, title=stt_title_hint(source).rstrip("."))
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

    # כתובית שנשארת על המסך אחרי שהדיבור בה נגמר. זה רץ לפני
    # finalize, שחותך לפי זמן קריאה בלבד ואינו יודע מתי הדובר
    # הפסיק — בעוד תזמוני המילים של המקור יושבים לנו ב-cue.words
    lingered = srt.trim_to_speech(cues)
    if lingered:
        log.info("קוצרו %d כתוביות שנשארו על המסך אחרי סוף הדיבור",
                 lingered)

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
    # segments ו-lines מיושרים לפי אינדקס — זו הנקודה היחידה שבה
    # שורת המקור והעברית שלה יושבות זו לצד זו. נכתב לתיקיית העבודה
    # כדי שכפתור "הוסף לזיכרון המובחר" יוכל לקרוא אותן אחר כך
    memory.write_pairs(work, [(seg.text, lines[seg.index])
                              for seg in transcript.segments
                              if seg.index < len(lines)])
    # והפלט שלנו נשמר לקורפוס ההשוואה. בלי הצד הזה אין keyness
    # בכלל: רשימת תדירות אחת אינה אומרת דבר. הקורפוס הזה אינו
    # "תרגומים טובים" ואינו נכנס לשום פרומפט כדוגמה — הוא החשוד
    idiom.remember_ours(lines, source=source.name)

    return Result(
        srt_path=srt_path, duration=duration, cues=len(cues),
        language=transcript.language, notes=notes,
        elapsed=time.monotonic() - started,
    )


async def translate_given(source: Path, srt_path: Path, work: Path,
                          on_progress=None, track: int = 0) -> Path:
    """מתרגם לעברית קובץ כתוביות שהמשתמש הביא — בלי לגעת בתזמונים.

    זה מסלול שלישי, לצד "תייצר לי כתוביות" ו"צרוב את הקובץ שלי כמו
    שהוא". ההבדל מהראשון הוא עקרוני: כשהמשתמש מביא קובץ מסונכרן,
    התזמונים שלו **נכונים** — והם הדבר שהכי קשה לנו לייצר. אין שום
    סיבה לייצר אותם מחדש ולהחליף דיוק ידוע בניחוש שלנו.

    ולכן כאן לא רצים build_cues, split, snap_to_cuts, close_gaps ולא
    finalize: כל אחד מהם מזיז זמנים. היחיד שכן רץ הוא שבירת שורות,
    שמשנה רק איפה נגמרת שורה בתוך הכתובית ולא מתי היא מופיעה.

    האודיו כן נסרק, אבל לא בשביל טקסט ולא בשביל זמנים — רק בשביל
    **מי מדבר**. בלי תוויות דובר המגדר נשען על ההקשר בלבד, וזו הנקודה
    שבה הוא נשבר. עם האודיו, "את הולכת" מול "אתה הולך" נקבע לפי הקול
    שנשמע באותה שנייה בדיוק, ולא לפי ניחוש מהטקסט
    """
    async def progress(text: str) -> None:
        if on_progress:
            await on_progress(text)

    cues = srt.parse(srt.read_subtitle(srt_path))
    if cues and config.SDH_STRIP:
        cleaned = srt.strip_sdh(cues)
        if cleaned:
            log.info("נוקו %d כתוביות מתיאורי צליל ושמות דוברים, נשארו %d",
                     cleaned, len(cues))
    if not cues:
        raise RuntimeError("לא הצלחתי לקרוא כתוביות מהקובץ ששלחת.")
    log.info("קובץ שהובא: %d כתוביות, %s עד %s", len(cues),
             srt.stamp(cues[0].start)[:8], srt.stamp(cues[-1].end)[:8])

    segments = [Segment(index=i, start=cue.start, end=cue.end,
                        text=" ".join((cue.text or "").split()))
                for i, cue in enumerate(cues)]

    # סריקת האודיו — רק לדוברים. כשל כאן אינו מפיל את העבודה: בלי
    # תוויות דובר התרגום עדיין רץ, רק שהמגדר חוזר להישען על ההקשר
    language = ""
    measured: dict[str, str] = {}
    if await media.has_audio(source):
        await progress("🎧 סורק את האודיו כדי לזהות מי מדבר…")
        try:
            audio = await media.extract_audio(source, work / "audio.flac",
                                              track)
            spoken = await gemini_stt.transcribe(audio)
        except Exception as exc:  # noqa: BLE001
            log.warning("סריקת הדוברים נכשלה (%s) — ממשיכים בלעדיה", exc)
            spoken = None
        if spoken and spoken.segments:
            language = spoken.language or ""
            tagged = _carry_speakers(segments, spoken.segments)
            log.info("תוויות דובר הוצמדו ל-%d מתוך %d כתוביות",
                     tagged, len(segments))
            # ומדידת המגדר מהקול עצמו. זה הרכיב שהבדיל אותנו מהכלים
            # המקצועיים: הם מודדים את תדר היסוד, ואנחנו הסקנו מהטקסט
            await progress("🎚️ מודד את המגדר מהקול…")
            heard: dict[str, list[tuple[float, float]]] = {}
            for seg in spoken.segments:
                who = getattr(seg, "speaker", "")
                if who:
                    heard.setdefault(who, []).append((seg.start, seg.end))
            try:
                verdicts = await voice.measure(audio, heard)
                measured = {v.speaker: v.gender
                            for v in verdicts.values() if v.sure}
            except Exception as exc:  # noqa: BLE001
                log.warning("מדידת המגדר מהקול נכשלה (%s)", exc)
        else:
            log.warning("לא התקבלו דוברים מהאודיו — המגדר יישען על ההקשר")
    else:
        log.warning("לקובץ אין ערוץ אודיו — אי אפשר לזהות דוברים")

    await progress("🇮🇱 מתרגם · חוקר את התוכן")

    async def on_step(note: str, fraction: float) -> None:
        await progress(f"🇮🇱 מתרגם · {note} · {fraction * 100:.0f}%")

    lines, _ = await hebrew.build_hebrew(
        segments, language or "auto", on_step=on_step,
        title=stt_title_hint(source).rstrip("."), measured=measured)

    # אותם זמנים בדיוק, טקסט חדש. wrap משנה רק היכן נשברת השורה
    out = [srt.Cue(index=i + 1, start=cue.start, end=cue.end,
                   text=srt.tidy_dialogue(
                       srt.wrap(lines[i] if i < len(lines) else cue.text)))
           for i, cue in enumerate(cues)]
    target = work / f"{source.stem}.he.srt"
    target.write_text(srt.render(out), encoding="utf-8")
    log.info("תורגמו %d כתוביות, התזמונים נשמרו כפי שהיו", len(out))
    memory.write_pairs(work, [(seg.text, lines[i])
                              for i, seg in enumerate(segments)
                              if i < len(lines)])
    idiom.remember_ours(lines, source=source.name)
    return target


def _carry_speakers(given: list[Segment], heard: list[Segment]) -> int:
    """מצמיד לכל כתובית שהובאה את הדובר שנשמע באותו זמן.

    ההצמדה לפי חפיפה בזמן ולא לפי טקסט, כי הטקסט של המשתמש והטקסט
    שהמודל שמע אינם זהים — ואין צורך שיהיו. מה שצריך להתאים זה רק
    המיקום על ציר הזמן, והוא מדויק בשני הצדדים
    """
    heard = sorted((s for s in heard if getattr(s, "speaker", "")),
                   key=lambda s: s.start)
    if not heard:
        return 0
    tagged = 0
    index = 0
    for cue in given:
        # מדלגים על כל מה שנגמר לפני תחילת הכתובית
        while index < len(heard) and heard[index].end <= cue.start:
            index += 1
        best, widest = "", 0.0
        look = index
        while look < len(heard) and heard[look].start < cue.end:
            overlap = (min(cue.end, heard[look].end)
                       - max(cue.start, heard[look].start))
            if overlap > widest:
                best, widest = heard[look].speaker, overlap
            look += 1
        if best:
            cue.speaker = best
            tagged += 1
    return tagged


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
