"""מגדר הדובר מהקול עצמו — מדידה אקוסטית, בלי מודל ובלי מפתחות.

זה הרכיב שהיה חסר לנו. עד כה המגדר הוסק מהטקסט: המודל קרא את
השורות וניחש מי גבר ומי אישה. הכלים המקצועיים לא מנחשים — הם
**מודדים** את תדר היסוד של הקול.

המספרים, מתוך מחקר פונטי: חציון של כ-113 הרץ אצל גברים וכ-181 אצל
נשים. אבל יש תחום חפיפה אמיתי, בערך 138 עד 163 הרץ, ושם אי אפשר
להכריע. הספרות מדגישה במפורש שתדר לבדו אינו מספיק — ולכן כאן הוא
אינו מחליף את ההסקה מהטקסט אלא עומד לצידה: כששניהם מסכימים יש
ודאות, וכשהמדידה בתחום החפיפה היא שותקת ונותנת לטקסט להכריע.

הזיהוי עצמו באוטוקורלציה. היא טועה כשפורמנט נופל ליד הרמוניה, ולכן
כל מסגרת נבדקת גם על בהירות המחזוריות ועל עוצמה, ומה שחוזר הוא
החציון של המסגרות ששרדו — לא ממוצע, שרגיש לחריגים.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

RATE = 16_000
FRAME = 640          # 40 אלפיות — מחזיק כמה מחזורים גם בקול נמוך
HOP = 320            # 20 אלפיות
F0_LOW, F0_HIGH = 70.0, 350.0     # טווח דיבור אנושי
CLARITY = 0.45       # כמה מחזורי הקול חייבים להיות ברורים
QUIET = 0.012        # מתחת לזה זו דממה או רעש רקע

# תחום ההכרעה. בין שני הערכים יש חפיפה אמיתית בין גברים לנשים,
# ושם המדידה שותקת במקום להמציא תשובה
MALE_BELOW = 138.0
FEMALE_ABOVE = 163.0

# כמה שניות של דיבור צריך כדי להכריע על דובר, וכמה מסגרות מזוהות
LEAST_SECONDS = 2.0
LEAST_FRAMES = 25

# כמה מהמסגרות חייבות להתרכז סביב החציון כדי שהמדידה תהיה תקפה.
#
# זה התנאי החשוב ביותר כאן, והוא נלמד מכישלון ממשי: המדידה הראשונה
# על קול של גבר החזירה "נקבה" בביטחון מלא. ההתפלגות גילתה למה —
# היא הייתה שטוחה לגמרי, 90 עד 260 הרץ באותה שכיחות. האוטוקורלציה
# לא עקבה אחרי הקול אלא אחרי מוזיקת הרקע, והחציון של רעש הוא מספר
# חסר משמעות שנפל במקרה בצד הנשי.
#
# קול אנושי אחד נותן פסגה צרה. התפלגות רחבה פירושה שמה שנמדד אינו
# קול יחיד — מוזיקה, כמה דוברים, או רעש — ואז שתיקה היא התשובה
# הנכונה. בסרט יש מוזיקה כמעט תמיד, ולכן בלי התנאי הזה הכלי היה
# מייצר שגיאות מגדר ודאיות במקום למנוע אותן
SPREAD = 0.20        # ±20% סביב החציון נחשב "סביב"
PACKED = 0.60        # ולפחות 60% מהמסגרות חייבות ליפול שם


@dataclass
class Verdict:
    speaker: str
    hertz: float
    frames: int
    gender: str      # "זכר" / "נקבה" / "" כשאין הכרעה
    packed: float = 0.0   # כמה מהמסגרות התרכזו סביב החציון

    @property
    def sure(self) -> bool:
        return bool(self.gender)


async def _pcm(audio: Path, spans: list[tuple[float, float]]) -> "list":
    """מחלץ את קטעי הדיבור של דובר אחד כ-PCM אחד רצוף."""
    import numpy as np

    pieces = []
    for start, end in spans:
        if end - start < 0.25:
            continue
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-v", "error",
            "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
            "-i", str(audio), "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", "1", "-ar", str(RATE), "-",
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        raw, _ = await proc.communicate()
        if raw:
            pieces.append(np.frombuffer(raw, dtype="<i2"))
    if not pieces:
        return np.array([], dtype="float32")
    return np.concatenate(pieces).astype("float32") / 32768.0


def pitch_track(samples) -> list[float]:
    """תדר היסוד בכל מסגרת שבה נשמע קול ברור.

    אוטוקורלציה מנורמלת: מחפשים את ההשהיה שבה האות הכי דומה לעצמו.
    ההשהיה הזאת היא אורך המחזור, וההופכי שלה הוא התדר
    """
    import numpy as np

    low = int(RATE / F0_HIGH)      # ההשהיה הקצרה ביותר שנבדקת
    high = int(RATE / F0_LOW)
    found: list[float] = []
    window = np.hanning(FRAME).astype("float32")

    for start in range(0, max(0, len(samples) - FRAME), HOP):
        frame = samples[start:start + FRAME]
        if float(np.sqrt(np.mean(frame * frame))) < QUIET:
            continue                      # דממה או רעש רקע
        frame = (frame - float(np.mean(frame))) * window
        energy = float(np.dot(frame, frame))
        if energy <= 0:
            continue
        # אוטוקורלציה דרך FFT — מהיר בהרבה מחישוב ישיר
        size = 1 << (2 * FRAME - 1).bit_length()
        spectrum = np.fft.rfft(frame, size)
        corr = np.fft.irfft(spectrum * np.conjugate(spectrum), size)[:high + 1]
        if len(corr) <= high or corr[0] <= 0:
            continue
        band = corr[low:high + 1]
        if not len(band):
            continue
        peak = int(np.argmax(band)) + low
        clarity = float(corr[peak] / corr[0])
        if clarity < CLARITY:
            continue                      # לא מחזורי מספיק — לא קול
        # דיוק תת-דגימתי: פרבולה על שלוש הנקודות סביב השיא
        if 0 < peak < high:
            before, here, after = corr[peak - 1], corr[peak], corr[peak + 1]
            bottom = before - 2 * here + after
            if bottom:
                peak += 0.5 * (before - after) / bottom
        hertz = RATE / peak if peak else 0.0
        if F0_LOW <= hertz <= F0_HIGH:
            found.append(hertz)
    return found


def decide(hertz: float) -> str:
    """מגדר לפי התדר, או מחרוזת ריקה בתחום החפיפה."""
    if hertz and hertz < MALE_BELOW:
        return "זכר"
    if hertz > FEMALE_ABOVE:
        return "נקבה"
    return ""


async def measure(audio: Path, spans: dict[str, list[tuple[float, float]]]
                  ) -> dict[str, Verdict]:
    """מודד את המגדר של כל דובר מהקול שלו.

    spans הוא מיפוי מדובר אל קטעי הזמן שבהם הוא נשמע
    """
    out: dict[str, Verdict] = {}
    for speaker, times in spans.items():
        heard = sum(end - start for start, end in times)
        if heard < LEAST_SECONDS:
            log.info("דובר %s: רק %.1f שניות דיבור — לא מודדים",
                     speaker, heard)
            continue
        samples = await _pcm(audio, times)
        if not len(samples):
            continue
        track = pitch_track(samples)
        if len(track) < LEAST_FRAMES:
            log.info("דובר %s: רק %d מסגרות קוליות — לא מכריעים",
                     speaker, len(track))
            continue
        middle = float(statistics.median(track))
        near = sum(1 for hz in track
                   if abs(hz - middle) <= middle * SPREAD)
        packed = near / len(track)
        if packed < PACKED:
            # לא קול יחיד: מוזיקה, כמה דוברים, או רעש. החציון כאן
            # הוא מספר חסר משמעות, ולכן לא מכריעים עליו
            log.info("דובר %s: ההתפלגות רחבה (%.0f%% סביב %.0f הרץ) — "
                     "כנראה מוזיקה או רעש, לא מכריעים",
                     speaker, packed * 100, middle)
            out[speaker] = Verdict(speaker, round(middle, 1), len(track),
                                   "", round(packed, 2))
            continue
        gender = decide(middle)
        out[speaker] = Verdict(speaker, round(middle, 1), len(track),
                               gender, round(packed, 2))
        log.info("דובר %s: %.0f הרץ · %.0f%% מרוכז · %d מסגרות ⇠ %s",
                 speaker, middle, packed * 100, len(track),
                 gender or "בתחום החפיפה")
    return out


def table(verdicts: dict[str, Verdict]) -> str:
    """שורת @מגדר לפרומפט, מהדוברים שהמדידה הכריעה עליהם בלבד."""
    sure = [v for v in verdicts.values() if v.sure]
    if not sure:
        return ""
    return "@מגדר: " + ", ".join(
        f"{v.speaker}={v.gender}" for v in sorted(sure, key=lambda v: v.speaker))
