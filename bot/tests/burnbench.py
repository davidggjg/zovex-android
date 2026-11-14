"""מודד את צוואר הבקבוק האמיתי בצריבה, על המכונה ועל הקובץ שלך.

למה זה קיים: הקצב המצרפי נפל ל-1.3x בעוד שתים-עשרה קטעים רצים
במקביל. ארבע השערות נבדקו במעבדה ונפסלו — ה-CRF עולה 14 אחוזים,
מקור 10bit עולה 6, הדגלים החדשים אפס, ותקרת הזיכרון כלל לא נגסה.

הנשאר הוא תחרות: קטע בודד שרץ לבדו מול כמה שרצים יחד. אם קטע בודד
מהיר והמצרפי לא גדל עם המקביליות — התחרות היא על הדיסק או על
הליבות, ולא על הקידוד. זה בדיוק מה שהמדידה הזאת מפרידה.

שימוש:
    python3 tests/burnbench.py /נתיב/לסרט.mkv
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SPAN = 60.0          # אורך כל קטע בבדיקה, שניות
OFFSET = 600.0       # מהיכן בסרט לקחת, כדי לא למדוד כותרות שחורות


async def one(src: Path, out: Path, start: float, threads: int,
              srt: Path) -> float:
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-t", f"{SPAN:.3f}",
        "-threads", str(threads), "-hwaccel", "auto", "-i", str(src),
        "-vf", f"subtitles='{srt}'",
        "-c:v", "libx265", "-preset", "superfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-tag:v", "hvc1",
        "-x265-params", f"pools={threads}:frame-threads=2:log-level=error",
        "-an", str(out),
    ]
    began = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    await proc.wait()
    return time.monotonic() - began


async def main() -> int:
    import os

    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"לא נמצא: {src}")
        return 2

    from zovexsub import config, media

    duration = await media.duration_seconds(src)
    cores = os.cpu_count() or 2
    threads = config.BURN_SEGMENT_THREADS
    print(f"{src.name} · {duration / 60:.0f} דקות · {cores} ליבות · "
          f"{threads} חוטים לקטע\n")

    work = Path(tempfile.mkdtemp(prefix="burnbench-"))
    srt = work / "t.srt"
    srt.write_text("1\n00:00:02,000 --> 00:00:58,000\nשורת בדיקה לכתוביות\n",
                   encoding="utf-8")

    print(f"{'במקביל':>7} | {'זמן הקטע':>9} | {'קצב קטע':>8} | {'מצרפי':>7}")
    print("-" * 44)
    best = 0.0
    try:
        for count in (1, 2, 4, 8, config.burn_slots(cores)):
            if count > 16:
                continue
            starts = [OFFSET + i * SPAN for i in range(count)]
            if starts[-1] + SPAN > duration:
                break
            began = time.monotonic()
            times = await asyncio.gather(*(
                one(src, work / f"o{count}_{i}.mp4", s, threads, srt)
                for i, s in enumerate(starts)))
            wall = time.monotonic() - began
            per = SPAN / (sum(times) / len(times))
            total = SPAN * count / wall
            best = max(best, total)
            print(f"{count:>7} | {sum(times) / len(times):>8.1f}ש׳ | "
                  f"{per:>7.2f}x | {total:>6.2f}x")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(f"\nהתפוקה המצרפית הטובה ביותר: {best:.2f}x")
    print("אם היא אינה גדלה עם המקביליות, הצוואר אינו הקידוד אלא "
          "הדיסק או הליבות.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
