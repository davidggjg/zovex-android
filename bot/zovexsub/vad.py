"""זיהוי דיבור אמיתי, להבדיל ממדידת עוצמת קול.

silencedetect של ffmpeg מודד אמפליטודה. בתוכן עם מוזיקת רקע — כלומר
כמעט בכל דרמה — המוזיקה חזקה מספיק כדי להיחשב "לא שקט", ולכן נספרת
כדיבור. התוצאה היא שכתובית שיושבת על קטע מוזיקלי "מוצאת דיבור" שם ולא
מוזזת, והיא מופיעה שניות לפני שמישהו פותח את הפה.

נמדד על קובץ בדיקה שבו הדיבור תופס 22% מהזמן:
  silencedetect   85% דיבור   (סופר את כל המוזיקה)
  Silero VAD      מוזיקה 0-3%, שקט 0%, דיבור 90-96%

Silero הוא מודל קטן (2.3MB) שרץ על מעבד. אם הוא או onnxruntime חסרים,
המודול מחזיר None והקוד נופל חזרה לשיטה הישנה.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from functools import lru_cache
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

RATE = 16000
WINDOW = 512          # גודל החלון שהמודל מצפה לו ב-16kHz
CONTEXT = 64          # דגימות הקשר שהמודל דורש לפני כל חלון
STATE = (2, 1, 128)


@lru_cache(maxsize=1)
def _session():
    """טוען את המודל פעם אחת. מחזיר None אם משהו חסר."""
    path = Path(config.VAD_MODEL)
    if not path.exists():
        log.warning("מודל ה-VAD לא נמצא ב-%s — נשארים בזיהוי לפי עוצמה", path)
        return None
    try:
        import onnxruntime
    except ImportError:
        log.warning("onnxruntime לא מותקן — נשארים בזיהוי לפי עוצמה")
        return None
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    return onnxruntime.InferenceSession(
        str(path), options, providers=["CPUExecutionProvider"])


def available() -> bool:
    return _session() is not None


def _decode(audio: Path) -> "object":
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-f", "s16le",
         "-ac", "1", "-ar", str(RATE), "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _probabilities(samples) -> list[float]:
    import numpy as np
    session = _session()
    state = np.zeros(STATE, dtype=np.float32)
    context = np.zeros(CONTEXT, dtype=np.float32)
    rate = np.array(RATE, dtype=np.int64)
    out = []
    for start in range(0, len(samples) - WINDOW, WINDOW):
        window = samples[start:start + WINDOW]
        # ההקשר הוא לא קישוט: בלעדיו המודל מחזיר אפס גם על דיבור אנושי
        value, state = session.run(
            None, {"input": np.concatenate([context, window])[None, :],
                   "state": state, "sr": rate})
        context = window[-CONTEXT:]
        out.append(float(value[0][0]))
    return out


def _spans(probabilities: list[float], threshold: float,
           pad: float, join: float, shortest: float) -> list[tuple[float, float]]:
    step = WINDOW / RATE
    spans: list[list[float]] = []
    start = None
    for index, value in enumerate(probabilities):
        if value >= threshold and start is None:
            start = index * step
        elif value < threshold and start is not None:
            spans.append([start, index * step])
            start = None
    if start is not None:
        spans.append([start, len(probabilities) * step])

    merged: list[list[float]] = []
    for span in spans:
        if merged and span[0] - merged[-1][1] <= join:
            merged[-1][1] = span[1]
        else:
            merged.append(span)
    return [(max(0.0, a - pad), b + pad) for a, b in merged if b - a >= shortest]


async def speech_spans(audio: Path) -> list[tuple[float, float]] | None:
    """קטעי הדיבור בקובץ, או None אם ה-VAD אינו זמין."""
    if not available():
        return None
    loop = asyncio.get_running_loop()
    try:
        samples = await loop.run_in_executor(None, _decode, audio)
        probabilities = await loop.run_in_executor(None, _probabilities, samples)
    except Exception as exc:  # noqa: BLE001 — עדיף השיטה הישנה מכישלון
        log.warning("זיהוי הדיבור נכשל (%s), נשארים בזיהוי לפי עוצמה", exc)
        return None

    spans = _spans(probabilities, config.VAD_THRESHOLD, config.VAD_PAD,
                   config.VAD_JOIN, config.VAD_MIN_SPEECH)
    total = len(probabilities) * WINDOW / RATE
    talking = sum(b - a for a, b in spans)
    log.info("VAD: %d קטעי דיבור, %.0f%% מהזמן", len(spans),
             talking / total * 100 if total else 0)
    return spans
