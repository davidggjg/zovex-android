"""בניית קובץ SRT: תזמונים נקיים ופיצול שורות קריא בעברית."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from . import config
from .stt import Segment

log = logging.getLogger(__name__)

# מילים שעדיף לא להשאיר בסוף שורה — הן פותחות את ההמשך
_OPENERS = {
    "של", "עם", "על", "אל", "את", "כי", "אם", "לא", "גם", "או", "כל", "זה",
    "אבל", "כדי", "לפני", "אחרי", "בתוך", "בגלל", "כמו", "יותר", "פחות",
    "אני", "אתה", "את", "הוא", "היא", "אנחנו", "אתם", "אתן", "הם", "הן",
}


@dataclass
class Cue:
    index: int
    start: float
    end: float
    text: str


# כמה מותר להזיז כתובית כדי להצמיד אותה לדיבור שזוהה. Whisper עובד
# בחלונות של 30 שניות, וכשחלון מלא מוזיקה הוא מחזיר כתובית שמתחילה
# בתחילת החלון — סטייה שיכולה להגיע לעשרות שניות.
MAX_SNAP = 25.0
# מקדימים את הכתובית במעט כדי לא לחתוך את ההברה הראשונה
LEAD_IN = 0.12


def build_cues(segments: list[Segment], lines: list[str],
               speech: list[tuple[float, float]] | None = None) -> list[Cue]:
    cues: list[Cue] = []
    for seg, hebrew in zip(segments, lines):
        text = (hebrew or "").strip()
        if not text:
            continue
        cues.append(Cue(0, seg.start, max(seg.end, seg.start + 0.3), text))

    if speech:
        cues = _snap_to_speech(cues, speech)
    cues = _fix_timing(cues)
    for i, cue in enumerate(cues, 1):
        cue.index = i
        cue.text = wrap(cue.text)
    return cues


def _snap_to_speech(cues: list[Cue], speech: list[tuple[float, float]]) -> list[Cue]:
    """מצמיד כל כתובית לדיבור שבאמת נשמע בתוכה.

    כתובית שמתחילה באמצע שקט נדחפת קדימה לרגע שבו הדיבור מתחיל, וסופה
    נמשך אחורה לרגע שבו הדיבור נגמר. בלי זה כתובית שהמודל מתח על פני
    שקט מופיעה שניות לפני שמישהו פותח את הפה.
    """
    moved = 0
    for cue in cues:
        inside = [(a, b) for a, b in speech if b > cue.start + 0.05 and a < cue.end - 0.05]
        if not inside:
            continue
        first = max(0.0, inside[0][0] - LEAD_IN)
        last = inside[-1][1]

        # הכתובית מתחילה בתוך שקט — דוחפים אותה לרגע שהדיבור מתחיל
        if 0.15 < first - cue.start <= MAX_SNAP and first < cue.end - 0.3:
            log.debug("כתובית הוזזה מ-%.2f ל-%.2f", cue.start, first)
            cue.start = first
            moved += 1
        # הכתובית נמשכת לתוך שקט — מושכים את סופה אחורה
        if 0.15 < cue.end - last <= MAX_SNAP and last > cue.start + 0.4:
            cue.end = last + 0.2

    log.info("הוצמדו %d כתוביות לדיבור שזוהה", moved)
    return cues


def _fix_timing(cues: list[Cue]) -> list[Cue]:
    """מונע חפיפות, אוכף אורך מינימלי/מקסימלי ומנצל שקט כדי להאריך קריאה."""
    for i, cue in enumerate(cues):
        nxt = cues[i + 1] if i + 1 < len(cues) else None

        if cue.end - cue.start > config.SRT_MAX_DURATION:
            cue.end = cue.start + config.SRT_MAX_DURATION

        if cue.end - cue.start < config.SRT_MIN_DURATION:
            room = (nxt.start - 0.08) if nxt else cue.start + config.SRT_MIN_DURATION
            cue.end = min(cue.start + config.SRT_MIN_DURATION, max(room, cue.end))

        # מהירות קריאה: עד ~17 תווים לשנייה. אם יש שקט אחרי — מאריכים.
        needed = len(cue.text) / 17.0
        if cue.end - cue.start < needed and nxt:
            cue.end = min(cue.start + needed, nxt.start - 0.08, cue.end + 2.0)

        if nxt and cue.end > nxt.start - 0.04:
            cue.end = max(cue.start + 0.3, nxt.start - 0.04)

    return [c for c in cues if c.end > c.start]


def wrap(text: str) -> str:
    """פיצול לשתי שורות מאוזנות, עם העדפה לשבירה בפיסוק ולא באמצע ביטוי."""
    text = " ".join(text.split())
    limit = config.SRT_MAX_CHARS_PER_LINE
    if len(text) <= limit:
        return text

    words = text.split(" ")
    best, best_score = None, float("inf")
    for cut in range(1, len(words)):
        first = " ".join(words[:cut])
        second = " ".join(words[cut:])
        if len(first) > limit or len(second) > limit * config.SRT_MAX_LINES:
            continue
        score = abs(len(first) - len(second))
        if first.rstrip().endswith((",", ".", "!", "?", ":", "—", "–", ";")):
            score -= 25
        if words[cut - 1] in _OPENERS:
            score += 18
        if second.startswith(("ו", "ש")) and len(words[cut]) <= 3:
            score += 6
        if score < best_score:
            best, best_score = (first, second), score

    if not best:
        return text
    first, second = best
    if len(second) > limit:
        return first + "\n" + wrap(second).replace("\n", " ")
    return first + "\n" + second


def stamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def render(cues: list[Cue]) -> str:
    blocks = [
        f"{cue.index}\n{stamp(cue.start)} --> {stamp(cue.end)}\n{cue.text}"
        for cue in cues
    ]
    return "\n\n".join(blocks) + "\n"


def parse(text: str) -> list[Cue]:
    """קורא קובץ SRT בחזרה לרשימת כתוביות."""
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timing = next((line for line in lines if "-->" in line), "")
        if not timing:
            continue
        try:
            left, right = timing.split("-->")
            start, end = _seconds(left), _seconds(right)
        except (ValueError, IndexError):
            continue
        body = "\n".join(lines[lines.index(timing) + 1:]).strip()
        if body:
            cues.append(Cue(len(cues) + 1, start, end, body))
    return cues


def _seconds(stamp: str) -> float:
    stamp = stamp.strip().replace(".", ",")
    hours, minutes, rest = stamp.split(":")
    secs, _, millis = rest.partition(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(secs) + int(millis or 0) / 1000


def slice_file(source: Path, start: float, end: float, dst: Path) -> Path:
    """עותק של הכתוביות לקטע אחד, מוזז כך שהקטע מתחיל בזמן אפס."""
    kept: list[Cue] = []
    for cue in parse(source.read_text(encoding="utf-8", errors="replace")):
        if cue.end <= start or cue.start >= end:
            continue
        kept.append(Cue(
            index=len(kept) + 1,
            start=max(0.0, cue.start - start),
            end=min(end, cue.end) - start,
            text=cue.text,
        ))
    # קטע בלי שום כתובית הוא מצב רגיל לגמרי — שתי דקות של שקט, מוזיקה או
    # קרדיטים. אבל מסנן הכתוביות של ffmpeg מסרב לפתוח קובץ בגודל אפס
    # ("Unable to open"), והקטע היה מפיל את כל הצריבה המקבילית חזרה
    # לתהליך יחיד. כתובית ריקה בת אלפית שנייה פותרת את זה ולא נראית
    if not kept:
        kept = [Cue(index=1, start=0.0, end=0.001, text=" ")]
    dst.write_text(render(kept), encoding="utf-8")
    return dst
