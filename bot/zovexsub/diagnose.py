"""אבחון תזמונים: מראה מה כל שלב החזיר, כדי לכוון לפי מספרים ולא לפי ניחוש."""
from __future__ import annotations

from pathlib import Path

from . import config, media, srt
from .stt import Transcript, transcribe


async def report(source: Path, work: Path) -> Path:
    lines: list[str] = []

    def w(text: str = "") -> None:
        lines.append(text)

    duration = await media.duration_seconds(source)
    audio = await media.extract_audio(source, work / "audio.flac")
    average = await media.mean_volume(audio)

    w("=== אבחון תזמונים ===")
    w(f"קובץ: {source.name}")
    w(f"אורך: {duration:.2f} שניות")
    w(f"עוצמת קול ממוצעת: {average:.1f}dB")
    w()

    w("--- כל הספים שנבדקו ---")
    for offset in (-9.0, -6.0, -3.0, 0.0, 3.0, 6.0):
        threshold = max(-50.0, min(-12.0, average - offset))
        spans = await media._detect(audio, threshold, 0.18, duration)
        ratio = sum(b - a for a, b in spans) / duration if duration else 0
        head = ", ".join(f"{a:.2f}-{b:.2f}" for a, b in spans[:6])
        w(f"סף {threshold:6.1f}dB | {len(spans):3d} קטעים | {ratio * 100:5.1f}% דיבור | {head}")
    w()

    chosen = await media.speech_spans(audio)
    w(f"--- הסף שנבחר: {len(chosen)} קטעי דיבור ---")
    for a, b in chosen[:60]:
        w(f"  {a:8.2f} -> {b:8.2f}")
    if len(chosen) > 60:
        w(f"  ... ועוד {len(chosen) - 60}")
    w()

    chunks = await media.split_audio(audio, work, duration)
    transcript: Transcript = await transcribe(chunks)
    w(f"--- התמלול: {len(transcript.segments)} סגמנטים, שפה {transcript.language} ---")
    w("אינדקס | Whisper התחלה-סוף | מילים | מילה ראשונה | טקסט")
    for seg in transcript.segments:
        first = f"{seg.words[0].start:8.2f}" if seg.words else "    אין"
        w(f"[{seg.index:3d}] {seg.start:8.2f}-{seg.end:8.2f} | {len(seg.words):3d} | "
          f"{first} | {seg.text[:45]}")
    w()

    cues = srt.build_cues(transcript.segments, [s.text for s in transcript.segments],
                          speech=chosen)
    w("--- אחרי ההצמדה ---")
    w("מספר | סופי התחלה-סוף | מקורי | הזזה | טקסט")
    for cue, seg in zip(cues, transcript.segments):
        shift = cue.start - seg.start
        flag = " <<<" if abs(shift) > 0.3 else ""
        w(f"[{cue.index:3d}] {cue.start:8.2f}-{cue.end:8.2f} | {seg.start:8.2f} | "
          f"{shift:+6.2f}{flag} | {cue.text.replace(chr(10), ' ')[:40]}")
    w()
    w(f"הגדרות: MAX_SNAP={srt.MAX_SNAP} LEAD_IN={srt.LEAD_IN} "
      f"TARGET={media.TARGET_SPEECH_RATIO}")

    out = work / "אבחון.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
