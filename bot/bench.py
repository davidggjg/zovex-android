"""מודד איזו הקצאת ליבות באמת מהירה יותר — על המכונה שלך, על הקובץ שלך.

הספרות לא נותנת את המספר. התיעוד של x265 מזהיר מהקצאת-יתר, פורומים
סותרים זה את זה, וכל מקור מסתיים באותו משפט: תמדוד בעצמך. זה הכלי.

במקום לשנות הגדרה ולהריץ סרט שלם כדי לגלות, נלקח קטע קצר אחד
ונצרב שוב ושוב בתצורות שונות. מה שנמדד הוא תפוקה מצרפית מול שעון
הקיר — כמה שניות וידאו נצרבו לשנייה אחת של זמן אמיתי — וזה המספר
היחיד שחשוב.

    python bench.py /tmp/zovexsub/XXXX/source.mkv
    python bench.py מקור.mkv --seconds 45 --at 600

⚠️ להריץ רק כשאין עבודה אחרת. הוא תופס את המכונה, וצריבה שרצה
   במקביל תזייף את כל המדידות.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

def current(cores: int) -> tuple[int, int]:
    """מה שרץ היום, לפי ההגדרות שבפועל — לא לפי מספר שהונח מראש.

    נמדד על השרת: BURN_SEGMENT_THREADS=3 ב-.env הפך את burn_slots(18)
    מ-18 ל-12, וכך 12 תהליכים על שלושה חוטים = 36 חוטים על 18 ליבות.
    בדיוק תור הריצה שנמדד. הגדרה שנקראת מהקובץ ולא מנוחשת
    """
    from zovexsub import config
    return config.burn_slots(cores), config.BURN_SEGMENT_THREADS


# התצורות שנבדקות: (כמה קטעים במקביל, כמה חוטי x265 לכל אחד).
# המכפלה היא סך החוטים — זה מה שמשווים מול מספר הליבות.
#
# שלוש הראשונות נותנות בדיוק חוט לליבה, ונבדלות רק בחלוקה בין
# תהליכים: הרבה תהליכים דקים מול מעט עבים. זו שאלה אמיתית, כי
# x265 לא מתרחב ליניארית עם מספר החוטים בתוך תהליך אחד
def plans(cores: int) -> list[tuple[int, int]]:
    return [
        (cores, 1),              # חוט לכל ליבה, תהליך לכל חוט
        (cores // 2, 2),         # אותו סך חוטים, חצי מהתהליכים
        (cores // 3, 3),         # אותו סך, שליש מהתהליכים
        (cores * 3 // 4, 2),     # הקצאת-יתר פי 1.5
        current(cores),          # ההגדרה שרצה היום, מה-.env
    ]


async def _encode(source: Path, start: float, length: float, threads: int,
                  out: Path) -> bool:
    """צורב קטע אחד. מחזיר האם הצליח."""
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", "-y",
        "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
        "-threads", str(threads), "-i", str(source),
        "-vf", "scale=-2:'min(1080,ih)':flags=lanczos",
        "-c:v", "libx265", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-x265-params", f"pools={threads}:frame-threads=2:log-level=none",
        "-an", str(out),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    await proc.wait()
    return proc.returncode == 0


async def run_plan(source: Path, at: float, seconds: float, slots: int,
                   threads: int, work: Path) -> float:
    """מריץ תצורה אחת ומחזיר תפוקה מצרפית (שניות וידאו לשנייה)."""
    work.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    # כל קטע מתחיל במקום אחר בסרט, בדיוק כמו בצריבה האמיתית —
    # אחרת היינו מודדים קריאה מהמטמון ולא מהדיסק
    jobs = [_encode(source, at + i * seconds, seconds, threads,
                    work / f"p{i}.mp4")
            for i in range(slots)]
    done = await asyncio.gather(*jobs)
    elapsed = time.monotonic() - started
    shutil.rmtree(work, ignore_errors=True)
    if not all(done) or elapsed <= 0:
        return 0.0
    return (slots * seconds) / elapsed


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="מודד הקצאת ליבות לצריבה, על המכונה והקובץ שלך")
    ap.add_argument("source", type=Path)
    ap.add_argument("--seconds", type=float, default=15.0,
                    help="אורך כל קטע במדידה (ברירת מחדל 15)")
    ap.add_argument("--at", type=float, default=300.0,
                    help="מאיזו שנייה בסרט להתחיל (ברירת מחדל 300)")
    args = ap.parse_args()

    if not args.source.exists():
        print(f"❌ אין קובץ: {args.source}")
        return 1

    busy = subprocess.run(["pgrep", "-c", "ffmpeg"], capture_output=True,
                          text=True).stdout.strip()
    if busy and busy.isdigit() and int(busy) > 0:
        print(f"⚠️  רצים כבר {busy} תהליכי ffmpeg על המכונה.")
        print("   המדידה תצא מזויפת לגמרי. חכה שהעבודה תסתיים.")
        return 1

    cores = os.cpu_count() or 2
    work = Path("/tmp/zovexbench")
    shutil.rmtree(work, ignore_errors=True)

    tried = [(s, t) for s, t in plans(cores) if s >= 1]
    seen: set[tuple[int, int]] = set()
    tried = [p for p in tried if not (p in seen or seen.add(p))]

    video = sum(s * args.seconds for s, _ in tried)
    print(f"🔬 {cores} ליבות · קטעים של {args.seconds:.0f}ש מדקה "
          f"{args.at / 60:.0f} · {len(tried)} תצורות")
    # הערכה לפי 0.6x, הקצב שנמדד בפועל. אם זה יותר מהר — ייגמר מוקדם
    print(f"   ייצרבו {video / 60:.0f} דקות וידאו · "
          f"צפוי כ-{video / 0.6 / 60:.0f} דקות\n")
    print("  קטעים  חוטים  סה\"כ חוטים   תפוקה")
    print("  " + "─" * 42)

    results: list[tuple[float, int, int]] = []
    for slots, threads in tried:
        rate = await run_plan(args.source, args.at, args.seconds,
                              slots, threads, work / f"{slots}x{threads}")
        results.append((rate, slots, threads))
        total = slots * threads
        mark = "  ← ההגדרה היום" if (slots, threads) == current(cores) else ""
        print(f"  {slots:>5}  {threads:>5}  {total:>10}   "
              f"{rate:>6.2f}x{mark}", flush=True)

    print("  " + "─" * 42)
    results.sort(reverse=True)
    best, slots, threads = results[0]
    if not best:
        print("\n❌ כל התצורות נכשלו — בדוק שה-ffmpeg תומך ב-libx265.")
        return 1

    now = next((r for r, s, t in results if (s, t) == current(cores)), 0.0)
    print(f"\n🏆 הכי מהיר: {slots} קטעים × {threads} חוטים = {best:.2f}x")
    if now and best > now * 1.05:
        gain = (best / now - 1) * 100
        print(f"   מהיר ב-{gain:.0f}% מההגדרה הנוכחית ({now:.2f}x).\n")
        over = slots * threads * 2 // cores or 1
        print("   להחיל:")
        print(f"     echo 'BURN_OVERSUBSCRIBE={over}' >> /opt/zovexsub/bot/.env")
        print(f"     echo 'BURN_SEGMENT_THREADS={threads}' >> "
              f"/opt/zovexsub/bot/.env")
        print("     systemctl restart zovexsub")
    elif now:
        print(f"   ההגדרה הנוכחית ({now:.2f}x) בתוך 5% מהטוב ביותר.")
        print("   אל תשנה כלום — ההבדל הוא רעש מדידה.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
