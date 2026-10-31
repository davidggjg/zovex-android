"""האם החורים בכתוביות הם שקט אמיתי, או דיבור שפוספס.

כלי קריאה בלבד. מריץ את אותו VAD שהצינור מריץ (Silero) על האודיו,
ומצליב מול הכתוביות: כל חור בכתוביות נבדק אם נשמע בו דיבור.

  חור על שקט      = תקין, אין שם מה לתמלל
  חור על דיבור    = שורות שפוספסו, וזה מה שצריך לתקן

שימוש:  python3 bot/gaps.py <וידאו-או-אודיו> <כתוביות.srt> [סף-שניות]
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zovexsub import media, srt, vad  # noqa: E402


def clock(value: float) -> str:
    return f"{int(value // 60)}:{int(value % 60):02d}"


async def main(source: Path, subtitles: Path, least: float) -> int:
    if not vad.available():
        print(f"ה-VAD אינו זמין (מודל ב-{Path(media.config.VAD_MODEL)})")
        return 1

    work = subtitles.parent / "_gapcheck"
    work.mkdir(parents=True, exist_ok=True)
    audio = work / "audio.flac"
    if source.suffix.lower() not in (".flac", ".wav"):
        print("מחלץ אודיו…")
        await media.extract_audio(source, audio)
    else:
        audio = source

    print("מריץ זיהוי דיבור…")
    speech = await vad.speech_spans(audio)
    if not speech:
        print("ה-VAD לא החזיר כלום")
        return 1

    cues = srt.parse(srt.read_subtitle(subtitles))
    cues.sort(key=lambda c: c.start)
    print(f"{len(cues)} כתוביות · {len(speech)} קטעי דיבור\n")

    holes = [(cues[i].end, cues[i + 1].start)
             for i in range(len(cues) - 1)
             if cues[i + 1].start - cues[i].end >= least]
    if cues:
        holes.insert(0, (0.0, cues[0].start))

    print(f"{'חור':<18} {'אורך':>7}  {'דיבור בפנים':>12}  מצב")
    print("-" * 62)
    missed = 0.0
    for begin, end in holes:
        if end - begin < least:
            continue
        heard = sum(min(end, stop) - max(begin, start)
                    for start, stop in speech
                    if start < end and stop > begin)
        state = "✅ שקט" if heard < 1.0 else "❌ דיבור שפוספס"
        if heard >= 1.0:
            missed += heard
        print(f"{clock(begin)}–{clock(end):<11} {end - begin:>6.0f}ש  "
              f"{heard:>11.0f}ש  {state}")

    talking = sum(stop - start for start, stop in speech)
    print(f"\nסך דיבור בסרט: {talking / 60:.1f} דקות")
    print(f"מתוכו בתוך חורים: {missed / 60:.1f} דקות "
          f"({missed / talking * 100 if talking else 0:.1f}%)")
    print("\nכל שורה עם ❌ היא דיבור שהמודל לא תמלל ושההצלה לא השלימה.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    edge = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
    raise SystemExit(asyncio.run(
        main(Path(sys.argv[1]), Path(sys.argv[2]), edge)))
