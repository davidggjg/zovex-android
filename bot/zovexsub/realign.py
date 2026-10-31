"""הקשבה חוזרת לקטעים שהתזמון שלהם חשוד.

Whisper מעבד אודיו בחלונות של 30 שניות. כשחלון מלא מוזיקה או שקט הוא
מאבד יישור ומחזיר כתובית שמתחילה בתחילת החלון, לפעמים שניות שלמות לפני
שמישהו פתח את הפה. במקום לנחש, כאן מקשיבים שוב — חותכים בדיוק את הקטע
שסביב הכתובית החשודה, שולחים אותו לתמלול בפני עצמו, ולוקחים את חותמת
המילה הראשונה שחוזרת. קטע מבודד כזה נופל בתחילת חלון חדש, ולכן היישור
שלו מדויק.
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import config, media
from .media import Chunk
from .stt import Segment, transcribe

log = logging.getLogger(__name__)

WINDOW = 30.0  # חלון העיבוד של Whisper


def _suspects(segments: list[Segment], speech: list[tuple[float, float]]) -> list[int]:
    """אילו כתוביות כדאי לשמוע שוב."""
    out = []
    for seg in segments:
        reasons = []

        # התחלה שנופלת בדיוק על גבול חלון — הסימן המובהק לאיבוד יישור
        if abs(seg.start % WINDOW) < 0.06:
            reasons.append("גבול חלון")
        # אין חותמות מילים, אז אין על מה להסתמך
        if not seg.words:
            reasons.append("בלי מילים")
        # ארוכה בהרבה ממה שהטקסט דורש
        if seg.end - seg.start > max(3.0, len(seg.text) / 11.0 + 2.0):
            reasons.append("ארוכה מדי")
        # מתחילה בתוך שקט לפי זיהוי הדיבור
        if speech:
            covering = [(a, b) for a, b in speech if a <= seg.start <= b]
            if not covering:
                after = [a for a, _ in speech if a > seg.start]
                if after and after[0] - seg.start > 0.4:
                    reasons.append("מתחילה בשקט")

        if reasons:
            log.info("[%d] חשוד (%s): %.2f-%.2f | %s",
                     seg.index, ", ".join(reasons), seg.start, seg.end, seg.text[:40])
            out.append(seg.index)
    return out


async def refine(segments: list[Segment], audio: Path, work: Path,
                 speech: list[tuple[float, float]], on_step=None) -> int:
    """מקשיב שוב לכתוביות החשודות ומתקן את זמן ההתחלה שלהן."""
    suspects = _suspects(segments, speech)
    if not suspects:
        log.info("אין כתוביות חשודות — אין צורך בהקשבה חוזרת")
        return 0

    budget = min(len(suspects), config.REALIGN_MAX)
    log.info("מקשיב שוב ל-%d כתוביות מתוך %d חשודות", budget, len(suspects))

    fixed = 0
    for n, index in enumerate(suspects[:budget]):
        seg = segments[index]
        previous = segments[index - 1] if index else None
        following = segments[index + 1] if index + 1 < len(segments) else None

        # חלון שמבודד את הכתובית מהשכנות שלה, עם מעט אוויר מסביב
        start = max(previous.end if previous else 0.0, seg.start - 2.0)
        end = min(following.start if following else seg.end + 2.0, seg.end + 2.0)
        if end - start < 0.4:
            continue

        if on_step:
            await on_step(n + 1, budget)
        clip = await media.cut_audio(audio, start, end, work / f"re{n:03d}.flac")
        try:
            again = await transcribe([Chunk(clip, start)])
        except RuntimeError as exc:
            log.warning("[%d] ההקשבה החוזרת נכשלה: %s", index, exc)
            continue
        finally:
            clip.unlink(missing_ok=True)

        onsets = [w.start for s in again.segments for w in s.words] or \
                 [s.start for s in again.segments]
        if not onsets:
            log.info("[%d] לא נשמע דיבור בקטע הזה", index)
            continue

        onset, offset = min(onsets), max(
            [w.end for s in again.segments for w in s.words] or
            [s.end for s in again.segments]
        )
        if not start - 0.1 <= onset <= end:
            continue
        # אותו ארטיפקט חוזר גם בקטע המבודד: אם המילה הראשונה מדווחת בדיוק
        # בתחילת הקטע שחתכנו, זה לא מידע — זו תחילת החלון
        if onset <= start + 0.2:
            log.info("[%d] ההקשבה החוזרת החזירה את תחילת הקטע — מתעלמים", index)
            continue

        shift = onset - seg.start
        if abs(shift) > 0.25:
            log.info("[%d] תוקן: %.2f -> %.2f (%+.2f) | %s",
                     index, seg.start, onset, shift, seg.text[:40])
            seg.start = onset
            seg.end = max(min(offset, end), onset + 0.4)
            fixed += 1

    log.info("ההקשבה החוזרת תיקנה %d כתוביות", fixed)
    return fixed
