"""יישור כפוי: מצמיד כל מילה למקום האמיתי שלה בגל הקול.

זה השורש של בעיית התזמונים. התזמונים ש-Whisper מחזיר הם ניחוש של
המודל, והם סוטים בסדר גודל של שנייה שלמה — זה מתועד ונמדד. VAD לא
פותר את זה: הוא יודע איפה יש דיבור, לא איזו מילה שייכת לאיזה רגע.

יישור כפוי עובד אחרת: לוקחים את הטקסט שכבר תומלל ומחפשים, מול האודיו
עצמו, את המסלול הסביר ביותר שמצמיד כל אות לפריים. נמדד כאן על אודיו
עם גבולות מילים ידועים: סטייה של 10 עד 40 מילישניות.

המודל הוא ייצוא ONNX של MMS-300M, תומך ב-1130 שפות, ורץ על אותו
onnxruntime שכבר משמש את ה-VAD — בלי PyTorch ובלי GPU.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import subprocess
import unicodedata
from functools import lru_cache
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

RATE = 16000
STRIDE = 320            # דגימות לפריים — 20 מילישניות
NEG = -1e30


@lru_cache(maxsize=1)
def _model():
    """טוען את המודל ואת אוצר המילים פעם אחת, או None אם חסר."""
    folder = Path(config.ALIGN_MODEL)
    weights = folder / "model.q8.onnx"
    vocabulary = folder / "vocab.json"
    if not weights.exists() or not vocabulary.exists():
        log.warning("מודל היישור לא נמצא ב-%s — התזמונים יישארו של Whisper",
                    folder)
        return None
    try:
        import onnxruntime
    except ImportError:
        log.warning("onnxruntime לא מותקן — אין יישור כפוי")
        return None
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = max(1, config.ALIGN_THREADS)
    options.log_severity_level = 3
    session = onnxruntime.InferenceSession(
        str(weights), options, providers=["CPUExecutionProvider"])
    return session, json.loads(vocabulary.read_text(encoding="utf-8"))


def available() -> bool:
    return _model() is not None


def romanize(text: str, vocabulary: dict) -> str:
    """מצמצם טקסט לאותיות שהמודל מכיר: a-z וגרש בלבד."""
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    folded = folded.replace("’", "'")
    folded = re.sub(r"[^a-z' ]+", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def _emissions(samples) -> "object":
    import numpy as np
    session, _ = _model()
    centred = samples - samples.mean()
    scaled = centred / math.sqrt((centred ** 2).mean() + 1e-7)
    batch = scaled[None, :].astype(np.float32)
    (logits,) = session.run(
        ["logits"], {"input_values": batch,
                     "attention_mask": np.ones(batch.shape, dtype=np.int64)})
    values = logits[0]
    values = values - values.max(-1, keepdims=True)
    return values - np.log(np.exp(values).sum(-1, keepdims=True))


def _viterbi(log_probs, targets: list[int], blank: int) -> list[int]:
    """המסלול הסביר ביותר של CTC, מווקטר.

    לולאה בפייתון על כל מצב ובכל פריים לוקחת נצח על חלון של חצי דקה,
    ולכן כל פריים מחושב כאן בפעולה אחת על מערך שלם.
    """
    import numpy as np

    frames = log_probs.shape[0]
    count = len(targets) * 2 + 1
    states = np.empty(count, dtype=np.int64)
    states[0::2] = blank
    states[1::2] = targets

    # דילוג על שני מצבים מותר רק כשהאות אינה חזרה על קודמתה
    skip = np.zeros(count, dtype=bool)
    if count > 2:
        skip[2:] = (states[2:] != blank) & (states[2:] != states[:-2])

    score = np.full(count, NEG)
    score[0] = log_probs[0, blank]
    if count > 1:
        score[1] = log_probs[0, states[1]]
    back = np.zeros((frames, count), dtype=np.int8)

    shift1 = np.full(count, NEG)
    shift2 = np.full(count, NEG)
    for frame in range(1, frames):
        shift1[1:] = score[:-1]
        shift2[2:] = np.where(skip[2:], score[:-2], NEG)
        stacked = np.stack((score, shift1, shift2))
        choice = stacked.argmax(axis=0)
        score = stacked[choice, np.arange(count)] + log_probs[frame, states]
        back[frame] = choice

    last = count - 1
    if count > 1 and score[count - 2] > score[count - 1]:
        last = count - 2
    path = [0] * frames
    path[-1] = last
    for frame in range(frames - 1, 0, -1):
        path[frame - 1] = path[frame] - int(back[frame, path[frame]])
    return path


def _word_times(words: list[str], path: list[int]) -> list[tuple[float, float]]:
    """גבולות הזמן של כל מילה, מתוך מסלול המצבים."""
    import numpy as np

    steps = np.asarray(path)
    seconds = STRIDE / RATE
    times: list[tuple[float, float]] = []
    index = 0
    for word in words:
        first, last = None, None
        for offset in range(len(word)):
            state = (index + offset) * 2 + 1
            frames = np.flatnonzero(steps == state)
            if frames.size:
                first = frames[0] if first is None else min(first, frames[0])
                last = frames[-1] if last is None else max(last, frames[-1])
        index += len(word)
        times.append((float(first) * seconds, float(last + 1) * seconds)
                     if first is not None else (0.0, 0.0))
    return times


def _decode(audio: Path, start: float, length: float) -> "object":
    """חותך קטע מהאודיו ומחזיר אותו כדגימות."""
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start):.3f}",
         "-t", f"{length:.3f}", "-i", str(audio), "-f", "s16le",
         "-ac", "1", "-ar", str(RATE), "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _windows(segments: list, limit: float) -> list[list[int]]:
    """מקבץ סגמנטים לחלונות שאפשר ליישר בבת אחת."""
    groups: list[list[int]] = []
    current: list[int] = []
    for index, segment in enumerate(segments):
        if current:
            span = segment.end - segments[current[0]].start
            gap = segment.start - segments[current[-1]].end
            if span > limit or gap > 3.0:
                groups.append(current)
                current = []
        current.append(index)
    if current:
        groups.append(current)
    return groups


def _align_window(audio: Path, segments: list, indices: list[int],
                  vocabulary: dict) -> list[tuple[int, float, float]]:
    """מיישר חלון אחד ומחזיר זמנים מוחלטים לכל סגמנט שבו."""
    pad = config.ALIGN_PAD
    begin = max(0.0, segments[indices[0]].start - pad)
    finish = segments[indices[-1]].end + pad

    spoken: list[str] = []
    owners: list[int] = []
    for index in indices:
        for word in romanize(segments[index].text, vocabulary).split():
            spoken.append(word)
            owners.append(index)
    if not spoken:
        return []

    targets = [vocabulary[c] for word in spoken for c in word]
    samples = _decode(audio, begin, finish - begin)
    # כל אות צריכה פריים אחד לפחות, ועוד אחד לכל חזרה רצופה
    needed = len(targets) + sum(1 for i in range(1, len(targets))
                                if targets[i] == targets[i - 1])
    if len(samples) // STRIDE <= needed:
        return []

    log_probs = _emissions(samples)
    path = _viterbi(log_probs, targets, vocabulary["<blank>"])
    times = _word_times(spoken, path)

    bounds: dict[int, list[float]] = {}
    for owner, (start, end) in zip(owners, times):
        if end <= start:
            continue
        edge = bounds.setdefault(owner, [start, end])
        edge[0] = min(edge[0], start)
        edge[1] = max(edge[1], end)
    return [(owner, begin + a, begin + b) for owner, (a, b) in bounds.items()]


async def refine(segments: list, audio: Path, on_step=None) -> int:
    """מתקן את זמני הסגמנטים לפי יישור מול האודיו. מחזיר כמה שונו."""
    loaded = _model()
    if loaded is None or not segments:
        return 0
    _, vocabulary = loaded

    groups = _windows(segments, config.ALIGN_WINDOW)
    log.info("יישור כפוי: %d חלונות על %d סגמנטים", len(groups), len(segments))
    # היישור נרשם באותה בריכת ליבות של הצריבה. בלי זה הוא לוקח את כל
    # המכונה בזמן שצריבה רצה לידו, ושניהם נחנקים — נמדד כצריבה שיורדת
    # מ-18x ל-4x כששני השלבים רצים יחד
    from . import media
    pool = media.core_pool()
    loop = asyncio.get_running_loop()
    moved = 0
    done = 0

    async def one(token: int, indices: list[int]) -> None:
        nonlocal moved, done
        async with pool.slot(token):
            try:
                fixed = await loop.run_in_executor(
                    None, _align_window, audio, segments, indices, vocabulary)
            except Exception as exc:  # noqa: BLE001 — עדיף תזמון ישן מכישלון
                log.warning("יישור חלון נכשל: %s", exc)
                fixed = []
        for index, start, end in fixed:
            segment = segments[index]
            if abs(segment.start - start) > 0.08:
                moved += 1
            segment.start = start
            segment.end = max(end, start + 0.25)
        done += 1
        if on_step:
            await on_step(done, len(groups))

    async with pool.job() as token:
        await asyncio.gather(*(one(token, group) for group in groups))
    log.info("היישור הזיז %d מתוך %d סגמנטים", moved, len(segments))
    return moved
