"""תמלול דרך gemini-3.5-transcribe — מודל תמלול ייעודי.

למה זה קיים: התזמונים ש-Whisper מחזיר הם ניחוש של המודל וסוטים בסדר
גודל של שנייה. המודל הזה הוא ASR ייעודי שמחזיר לכל מילה התחלה וסוף
במילישניות, וגם מי אמר אותה. כלומר שתי הבעיות הגדולות — תזמונים ומגדר
הפנייה — נפתרות במקור במקום להיות מתוקנות אחר כך.

מגבלה של המודל: כשתזמוני מילים פעילים הוא מקבל עד שלושים דקות אודיו
לבקשה, ולכן הקובץ נחתך לחלקים עם חפיפה.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from . import config, media
from .stt import Segment, Transcript, Word

log = logging.getLogger(__name__)

MODEL = "gemini-3.5-transcribe"


def available() -> bool:
    if not config.GEMINI_API_KEYS or not config.GEMINI_STT:
        return False
    try:
        __import__("google.genai")
    except ImportError:
        log.warning("google-genai לא מותקן — אין תמלול דרך ג'מיני")
        return False
    return True


def _config(diarize: bool) -> dict:
    mode: dict = {"type": "verbatim", "timestamp_granularities": ["word"]}
    if diarize:
        mode["diarization_mode"] = "speaker"
    return {"transcription_config": {"language_codes": [], "mode": mode}}


def _language_of(interaction) -> str:
    """שפת המקור, אם המודל מדווח עליה."""
    for step in getattr(interaction, "steps", None) or []:
        for content in getattr(step, "content", None) or []:
            for field in ("language_code", "language"):
                found = getattr(content, field, None)
                if found:
                    return str(found)
    return ""


def _words_of(interaction) -> list[dict]:
    """שולף את הערות ה-word_info שהמודל מחזיר."""
    found: list[dict] = []
    for step in getattr(interaction, "steps", None) or []:
        for content in getattr(step, "content", None) or []:
            for note in getattr(content, "annotations", None) or []:
                if getattr(note, "type", None) != "word_info":
                    continue
                text = (getattr(note, "text", "") or "").strip()
                start = _seconds(getattr(note, "start_offset", None))
                end = _seconds(getattr(note, "end_offset", None))
                if text and start is not None and end is not None and end > start:
                    found.append({"text": text, "start": start, "end": end,
                                  "speaker": getattr(note, "speaker", None) or ""})
    found.sort(key=lambda w: (w["start"], w["end"]))
    return found


def _seconds(value) -> float | None:
    """ההיסט מגיע כמחרוזת, כמספר או כאובייקט משך — מנרמל לשניות."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    for attribute in ("total_seconds", "seconds"):
        found = getattr(value, attribute, None)
        if callable(found):
            return float(found())
        if found is not None:
            return float(found)
    text = str(value).strip().rstrip("s")
    try:
        return float(text)
    except ValueError:
        return None


def _one_chunk(path: Path, key: str, diarize: bool) -> list[dict]:
    """מעלה קטע, מתמלל אותו ומוחק אותו מהשרת של גוגל."""
    from google import genai

    client = genai.Client(api_key=key)
    uploaded = None
    try:
        uploaded = client.files.upload(file=str(path))
        interaction = client.interactions.create(
            model=MODEL,
            input=[{"type": "audio", "uri": uploaded.uri,
                    "mime_type": uploaded.mime_type}],
            generation_config=_config(diarize),
        )
        return _words_of(interaction), _language_of(interaction)
    finally:
        if uploaded is not None:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:  # noqa: BLE001 — ניקוי לא אמור להפיל כלום
                pass


async def _chunk_words(path: Path, diarize: bool) -> tuple[list[dict], bool, str]:
    """מתמלל קטע אחד, מסובב מפתחות, ומוותר על זיהוי דוברים אם הוא נדחה."""
    loop = asyncio.get_running_loop()
    last = None
    for key in config.GEMINI_API_KEYS:
        try:
            words, tongue = await loop.run_in_executor(
                None, _one_chunk, path, key, diarize)
            if words:
                return words, diarize, tongue
            last = RuntimeError("התמלול חזר בלי תזמוני מילים")
        except Exception as exc:  # noqa: BLE001 — מנסים את המפתח הבא
            last = exc
            text = str(exc).lower()
            # התיעוד מראה זיהוי דוברים יחד עם תזמונים, אבל חלק
            # מהשילובים נדחים. במקרה כזה מוותרים על הדוברים ולא על הכל
            if diarize and ("diariz" in text or "invalid" in text
                            or "not supported" in text):
                log.warning("זיהוי דוברים נדחה — ממשיכים בלעדיו")
                diarize = False
                continue
            log.warning("מפתח נכשל בקטע: %s", str(exc)[:120])
            await asyncio.sleep(1)
    raise RuntimeError(f"כל המפתחות נכשלו: {last}")


def _segments(words: list[dict]) -> list[Segment]:
    """מקבץ מילים לשורות כתוביות, בלי לגעת בתזמונים עצמם."""
    out: list[Segment] = []
    current: list[dict] = []
    letters = 0

    def flush() -> None:
        nonlocal current, letters
        if not current:
            return
        out.append(Segment(
            index=len(out),
            start=current[0]["start"],
            end=current[-1]["end"],
            text=" ".join(w["text"] for w in current).strip(),
            words=[Word(w["start"], w["end"], w["text"]) for w in current],
            speaker=current[0].get("speaker", ""),
        ))
        current, letters = [], 0

    for word in words:
        if current:
            gap = word["start"] - current[-1]["end"]
            changed = (word.get("speaker") or "") != (current[-1].get("speaker") or "")
            if (gap >= config.GEMINI_STT_PAUSE or changed
                    or len(current) >= config.GEMINI_STT_WORDS
                    or letters + len(word["text"]) > config.GEMINI_STT_CHARS):
                flush()
        current.append(word)
        letters += len(word["text"]) + 1
    flush()
    return out


async def transcribe(audio: Path, on_step=None) -> Transcript | None:
    """מתמלל קובץ שלם. מחזיר None אם הספק אינו זמין או נכשל."""
    if not available():
        return None

    total = await media.duration_seconds(audio)
    span = config.GEMINI_STT_CHUNK
    overlap = config.GEMINI_STT_OVERLAP
    starts = [s for s in _range(0.0, total, span - overlap)]
    log.info("תמלול ג'ימיני: %d חלקים של %.0f דקות", len(starts), span / 60)

    work = audio.parent / "gstt"
    work.mkdir(parents=True, exist_ok=True)
    collected: list[dict] = []
    diarize = config.GEMINI_STT_SPEAKERS
    tongue = ""
    done = 0

    # החלקים רצים במקביל, מפתח לכל אחד. קודם זו הייתה לולאה סדרתית —
    # חלק אחד מועלה ומתומלל, ורק אז הבא — וסרט של שעתיים לקח שמונה
    # סבבים בטור בזמן שתשעה מפתחות עמדו בטלה
    gate = asyncio.Semaphore(max(1, len(config.GEMINI_API_KEYS)))
    results: dict[int, list[dict]] = {}
    found_any = [""]
    flags = [diarize]

    async def one(index: int, begin: float) -> None:
        nonlocal done
        length = min(span, total - begin)
        if length <= 0.5:
            return
        async with gate:
            piece = work / f"part{index:03d}.wav"
            await media.cut_audio(audio, begin, begin + length, piece)
            try:
                words, flags[0], found = await _chunk_words(piece, flags[0])
            finally:
                piece.unlink(missing_ok=True)
        found_any[0] = found_any[0] or found
        results[index] = [{**w, "start": begin + w["start"],
                           "end": begin + w["end"]} for w in words]
        done += 1
        if on_step:
            await on_step(done, len(starts))

    try:
        await asyncio.gather(*(one(i, b) for i, b in enumerate(starts)))
        tongue = found_any[0]
        # ההרכבה לפי הסדר, והחפיפה מסוננת כאן ולא תוך כדי
        for index in sorted(results):
            for word in results[index]:
                if collected and word["start"] < collected[-1]["end"] - 0.05:
                    continue
                collected.append(word)
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)

    if not collected:
        return None
    segments = _segments(collected)
    speakers = {s.speaker for s in segments if s.speaker}
    log.info("ג'ימיני תמלל %d מילים ב-%d שורות%s", len(collected), len(segments),
             f", {len(speakers)} דוברים" if speakers else "")
    # בלי שפה מוצהרת, הפרומפטים של החקר והתרגום מקבלים שדה ריק. עדיף
    # לומר למודל לזהות בעצמו מאשר להשאיר אותו ריק
    return Transcript(language=tongue or "לא צוינה — זהה אותה מהתמליל",
                      segments=segments)


def _range(start: float, stop: float, step: float) -> list[float]:
    values = []
    while start < stop:
        values.append(start)
        start += step
    return values
