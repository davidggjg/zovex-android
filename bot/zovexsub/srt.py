"""בניית קובץ SRT: תזמונים נקיים ופיצול שורות קריא בעברית."""
from __future__ import annotations

from dataclasses import dataclass

from . import config
from .stt import Segment

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


def build_cues(segments: list[Segment], lines: list[str]) -> list[Cue]:
    cues: list[Cue] = []
    for seg, hebrew in zip(segments, lines):
        text = (hebrew or "").strip()
        if not text:
            continue
        cues.append(Cue(0, seg.start, max(seg.end, seg.start + 0.3), text))

    cues = _fix_timing(cues)
    for i, cue in enumerate(cues, 1):
        cue.index = i
        cue.text = wrap(cue.text)
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
