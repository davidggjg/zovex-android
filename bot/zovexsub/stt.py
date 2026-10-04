"""תמלול עם Groq Whisper large-v3 — חותמות זמן ברמת סגמנט ומילה."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import config, media
from .keypool import KeyPool
from .media import Chunk

log = logging.getLogger(__name__)

URL = "https://api.groq.com/openai/v1/audio/transcriptions"


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    index: int
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    no_speech: float = 0.0


@dataclass
class Transcript:
    language: str
    segments: list[Segment]

    @property
    def plain(self) -> str:
        return " ".join(s.text for s in self.segments)


async def _post_chunk(client: httpx.AsyncClient, pool: KeyPool, chunk: Chunk,
                      prompt: str | None, model: str) -> dict | None:
    """שולח קטע לתמלול. מחזיר None אם הספק לא הצליח לענות אחרי כל הנסיונות.

    502 ו-503 מ-Groq הם עומס זמני אצלם ולא תקלה בקובץ, ולכן מנסים שוב
    בסבלנות ומחליפים מפתח בכל פעם. שגיאה שמעידה על הקובץ עצמו נזרקת מיד.
    """
    data = {
        "model": model,
        "response_format": "verbose_json",
        "timestamp_granularities[]": ["segment", "word"],
        "temperature": "0",
    }
    if prompt:
        data["prompt"] = prompt[:800]

    last_error = "לא ידוע"
    for attempt in range(1, config.STT_ATTEMPTS + 1):
        key = await pool.wait_for_free()
        with chunk.path.open("rb") as fh:
            files = {"file": (chunk.path.name, fh, "audio/flac")}
            try:
                resp = await client.post(
                    URL, headers={"Authorization": f"Bearer {key}"},
                    data=data, files=files, timeout=httpx.Timeout(900.0, connect=30.0),
                )
            except httpx.HTTPError as exc:
                last_error = f"רשת: {exc}"
                await asyncio.sleep(min(2 ** attempt, 60))
                continue

        if resp.status_code == 200:
            pool.report_ok(key)
            return resp.json()

        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            pool.penalize(key, float(retry_after) if retry_after else None)
            last_error = "מכסה"
            await asyncio.sleep(min(2 ** attempt, 30))
            continue

        if resp.status_code >= 500:
            # תקלה אצל הספק. מחליפים מפתח ומחכים יותר בכל סיבוב
            pool.penalize(key, 15)
            last_error = f"HTTP {resp.status_code} אצל Groq"
            wait = min(5 * attempt, 60)
            log.warning("%s (נסיון %d/%d), ממתין %ds",
                        last_error, attempt, config.STT_ATTEMPTS, wait)
            await asyncio.sleep(wait)
            continue

        if resp.status_code in (401, 403):
            pool.penalize(key, 3600)
            last_error = f"מפתח נדחה (HTTP {resp.status_code})"
            continue

        if resp.status_code == 413:
            log.warning("הקטע גדול מדי עבור ה-API")
            return None

        if resp.status_code == 404:
            # Groq מסירים ומחליפים מודלים מדי פעם — עוברים לבא בתור
            log.warning("המודל %s אינו קיים אצל Groq", model)
            return None

        raise RuntimeError(f"Groq החזיר HTTP {resp.status_code}: {resp.text[:300]}")

    log.warning("הקטע לא תומלל במודל %s: %s", model, last_error)
    return None


async def _transcribe_chunk(client: httpx.AsyncClient, pool: KeyPool, chunk: Chunk,
                            prompt: str | None, work: Path, depth: int = 0) -> dict | None:
    """מנסה מודל ראשי, אחריו מודל גיבוי, ולבסוף מפצל את הקטע לשניים."""
    for model in (config.GROQ_STT_MODEL, config.GROQ_STT_FALLBACK):
        if not model:
            continue
        payload = await _post_chunk(client, pool, chunk, prompt, model)
        if payload is not None:
            if model != config.GROQ_STT_MODEL:
                log.info("הקטע תומלל במודל הגיבוי %s", model)
            return payload

    # ייתכן שהקטע עצמו בעייתי או גדול מדי — מנסים אותו בשני חצאים
    if depth >= 2:
        return None
    length = await media.duration_seconds(chunk.path)
    if length < 60:
        return None

    log.warning("מפצל קטע של %.0f שניות ומנסה שוב", length)
    middle = length / 2
    merged: dict = {"segments": [], "words": [], "language": ""}
    for part, (begin, end) in enumerate(((0.0, middle), (middle, length))):
        piece = work / f"{chunk.path.stem}_{depth}{part}.flac"
        await media.cut_audio(chunk.path, begin, end, piece)
        half = Chunk(piece, chunk.offset + begin)
        payload = await _transcribe_chunk(client, pool, half, prompt, work, depth + 1)
        piece.unlink(missing_ok=True)
        if payload is None:
            continue
        merged["language"] = merged["language"] or payload.get("language", "")
        for seg in payload.get("segments") or []:
            seg = dict(seg)
            seg["start"] = float(seg.get("start", 0)) + begin
            seg["end"] = float(seg.get("end", 0)) + begin
            merged["segments"].append(seg)
        for word in payload.get("words") or []:
            word = dict(word)
            word["start"] = float(word.get("start", 0)) + begin
            word["end"] = float(word.get("end", 0)) + begin
            merged["words"].append(word)

    return merged if merged["segments"] else None


async def transcribe(chunks: list[Chunk], *, hint: str | None = None,
                     on_chunk=None, work: Path | None = None) -> Transcript:
    pool = KeyPool("groq", config.GROQ_API_KEYS)
    segments: list[Segment] = []
    language = ""
    failed: list[int] = []
    carry = hint  # הטקסט מהחלק הקודם משמש כקונטקסט להמשכיות

    async with httpx.AsyncClient() as client:
        for n, chunk in enumerate(chunks, 1):
            log.info("מתמלל חלק %d/%d", n, len(chunks))
            payload = await _transcribe_chunk(
                client, pool, chunk, carry, work or chunk.path.parent)
            if payload is None:
                # לא מאבדים את מה שכבר תומלל בגלל קטע אחד שנכשל
                log.error("חלק %d/%d לא תומלל — ממשיכים בלעדיו", n, len(chunks))
                failed.append(n)
                if on_chunk:
                    await on_chunk(n, len(chunks))
                continue
            language = language or (payload.get("language") or "")
            raw_segments = payload.get("segments") or []
            raw_words = payload.get("words") or []

            for seg in raw_segments:
                text = (seg.get("text") or "").strip()
                if not text:
                    continue
                start = float(seg.get("start", 0.0)) + chunk.offset
                end = float(seg.get("end", start)) + chunk.offset
                words = [
                    Word(float(w["start"]) + chunk.offset, float(w["end"]) + chunk.offset,
                         str(w.get("word", "")).strip())
                    for w in raw_words
                    if w.get("start") is not None
                    and start - chunk.offset - 0.01 <= float(w["start"]) <= end - chunk.offset + 0.01
                ]
                if words:
                    # חותמות המילים מדויקות בהרבה מגבולות הסגמנט, שנוטים
                    # להקדים את תחילת הדיבור ולהימשך לתוך השקט שאחריו
                    first, last = words[0].start, words[-1].end
                    if start - 2.0 <= first <= end:
                        start = first
                    if start <= last <= end + 2.0:
                        end = last

                segments.append(Segment(
                    index=len(segments),
                    start=start,
                    end=max(end, start + 0.2),
                    text=text,
                    words=words,
                    no_speech=float(seg.get("no_speech_prob") or 0.0),
                ))

            if raw_segments:
                carry = " ".join((s.get("text") or "") for s in raw_segments[-4:]).strip()
            if on_chunk:
                await on_chunk(n, len(chunks))

    if failed:
        log.error("%d מתוך %d קטעים לא תומללו: %s",
                  len(failed), len(chunks), ", ".join(map(str, failed)))
    if not segments and failed:
        raise RuntimeError(
            "התמלול נכשל: Groq לא הגיב לאף קטע. זו תקלה זמנית אצלם — נסה שוב בעוד כמה דקות."
        )

    segments = _drop_hallucinations(segments)
    for i, seg in enumerate(segments):
        seg.index = i
    return Transcript(language=language or "unknown", segments=segments)


_URL = re.compile(r"(https?://|www\.|\.(com|net|org|tv|ru|ir|co\.il)\b)", re.I)

_JUNK = {
    "תרגום וכתוביות", "כתוביות", "סוף", "תודה רבה", "thank you", "thanks for watching",
    "subtitles by", "amara.org", "please subscribe", "משנה הבאה",
}


def _drop_hallucinations(segments: list[Segment]) -> list[Segment]:
    """Whisper נוטה להמציא טקסט על קטעי שקט. מסננים את החשודים."""
    clean: list[Segment] = []
    for seg in segments:
        low = seg.text.strip().lower().strip(".!?,- ")
        if seg.no_speech > 0.75 and len(low) < 40:
            continue
        if any(j in low for j in _JUNK) and len(low) < 45:
            continue
        # כתובת אתר או סימן מים — כמעט תמיד המצאה של המודל, לא דיבור
        if _URL.search(low) and len(low) < 60:
            continue
        # שכפול זהה רצוף
        if clean and clean[-1].text.strip() == seg.text.strip() and seg.end - seg.start < 1.5:
            clean[-1].end = max(clean[-1].end, seg.end)
            continue
        clean.append(seg)
    return clean
