"""מודד סטיית תזמון לאורך הסרט, ואומר איזה סוג סטייה זו.

למה זה קיים: דווח שבסרט ארוך התזמונים "מדקה מסוימת מתחילים להיות
גרועים". זו חתימה של הצטברות, לא של רעש — אבל יש כמה מקורות אפשריים,
וכל אחד דורש תיקון אחר. במקום לנחש, מודדים.

הכלי משווה את זמני הכתוביות לדיבור שזוהה באודיו, ומפרק את הסטייה
לפי חלונות של עשר דקות. צורת העקומה היא שמזהה את האשם:

  סטייה קבועה לאורך כל הסרט      -> היסט גלובלי, כבר מטופל
  גדלה ברציפות מההתחלה לסוף      -> סטייה מצטברת בציר הזמן
  מתאפסת כל N דקות ואז גדלה שוב  -> סטייה בתוך מקטע תמלול, N = אורך המקטע
  קופצת בנקודה אחת ונשארת        -> מקטע יחיד עם היסט שגוי

שימוש:
    python3 tests/drift.py <וידאו או אודיו> <קובץ srt>
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BUCKET = 600.0          # חלון מדידה, שניות
NEAR = 4.0              # מעבר לזה אין התאמה אמיתית בין כתובית לדיבור


async def main() -> int:
    from zovexsub import config, media, srt as srt_tools, vad

    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    source, srt_path = Path(sys.argv[1]), Path(sys.argv[2])
    for path in (source, srt_path):
        if not path.exists():
            print(f"לא נמצא: {path}")
            return 2

    if not vad.available():
        print("Silero VAD אינו מותקן — בלעדיו אין מול מה להשוות")
        return 2

    cues = srt_tools.parse(srt_path.read_text(encoding="utf-8"))
    print(f"{len(cues)} כתוביות")

    audio = source
    if source.suffix.lower() not in {".wav", ".flac"}:
        audio = source.with_suffix(".drift.flac")
        print("מחלץ אודיו…")
        await media.extract_audio(source, audio)

    print("מריץ זיהוי דיבור…")
    speech = await vad.speech_spans(audio)
    if not speech:
        print("לא זוהה דיבור")
        return 1
    starts = [begin for begin, _ in speech]

    # לכל כתובית, המרחק אל תחילת הדיבור הקרובה ביותר. חיובי = הכתובית
    # מאחרת אחרי הדיבור, שלילי = מקדימה אותו
    buckets: dict[int, list[float]] = {}
    for cue in cues:
        nearest = min(starts, key=lambda s: abs(s - cue.start))
        gap = cue.start - nearest
        if abs(gap) > NEAR:
            continue
        buckets.setdefault(int(cue.start // BUCKET), []).append(gap)

    if not buckets:
        print("אף כתובית לא נפלה ליד דיבור — הסטייה גדולה מדי למדידה הזאת")
        return 1

    print(f"\n{'דקות':>12} | {'כתוביות':>8} | {'סטייה ממוצעת':>13} | גרף")
    print("-" * 64)
    values = []
    for key in sorted(buckets):
        gaps = buckets[key]
        mean = sum(gaps) / len(gaps)
        values.append(mean)
        span = f"{int(key * BUCKET // 60)}-{int((key + 1) * BUCKET // 60)}"
        bar = "█" * min(20, int(abs(mean) * 10))
        side = "מאחר" if mean > 0 else "מקדים"
        print(f"{span:>12} | {len(gaps):>8} | {mean:>+10.2f}ש׳ | {bar} {side}")

    swing = max(values) - min(values)
    print(f"\nטווח הסטייה בין החלונות: {swing:.2f} שניות")
    if swing < 0.3:
        print("אין הצטברות. הסטייה אחידה — זה היסט גלובלי בלבד.")
    elif values[-1] - values[0] > 0.8 * swing:
        print("הסטייה גדלה ברציפות — הצטברות לאורך ציר הזמן.")
    else:
        print("הסטייה אינה חד-כיוונית — חפשו חלון בודד שחורג בטבלה למעלה.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
