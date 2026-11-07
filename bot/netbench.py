"""מודד כמה חיבורים באמת מנצלים את הרשת של השרת בהעלאה לטלגרם.

‏TG_CONNECTIONS הוא מספר קבוע שמישהו ניחש פעם. השרת הזה יושב בחוות
שרתים עם רוחב פס גדול, ואין שום סיבה להאמין שהמספר הזה הוא הנכון
עבורו — לא למעלה ולא למטה.

כאן אותו קובץ בדיוק מועלה שוב ושוב, בכל פעם במספר חיבורים אחר,
והמדד הוא מגה-בייט לשנייה בפועל. זו המדידה היחידה שיכולה להכריע.

    python netbench.py                  # 200MB, חמישה מספרי חיבורים
    python netbench.py --mb 400         # קובץ גדול יותר, מדידה יציבה יותר
    python netbench.py --try 8,16,32    # רק את אלה

⚠️ הבוט חייב להיות עצור — הוא מחזיק את אותו סשן.

החלקים מועלים ואינם נשלחים לאיש. טלגרם זורקת חלקים שלא הורכבו
לקובץ, ולכן שום הודעה אינה נוצרת ושום מקום אחסון אינו נתפס.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from zovexsub import config, fastio          # noqa: E402


def bot_running() -> bool:
    out = subprocess.run(["systemctl", "is-active", "zovexsub"],
                         capture_output=True, text=True).stdout.strip()
    return out == "active"


async def measure(client, path: Path, size: int, workers: int) -> float:
    """מעלה את הקובץ ב-workers חיבורים. מחזיר מגה-בייט לשנייה."""
    parts = -(-size // fastio.PART)
    started = time.monotonic()
    try:
        await fastio._parallel_upload(client, path, size, parts,
                                      workers, None)
    except Exception as exc:  # noqa: BLE001
        print(f"      נכשל: {type(exc).__name__}: {str(exc)[:80]}")
        return 0.0
    spent = time.monotonic() - started
    return (size / 1048576) / spent if spent > 0 else 0.0


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="מודד כמה חיבורים מנצלים את הרשת בהעלאה")
    ap.add_argument("--mb", type=int, default=200,
                    help="גודל קובץ המבחן (ברירת מחדל 200)")
    ap.add_argument("--try", dest="counts", default="4,8,16,24,32",
                    help="מספרי החיבורים לבדיקה")
    args = ap.parse_args()

    if bot_running():
        print("⚠️  הבוט רץ ומחזיק את אותו סשן.")
        print("   systemctl stop zovexsub   ואז להריץ שוב.")
        return 1

    counts = sorted({int(c) for c in args.counts.split(",") if c.strip()})
    size = args.mb * 1048576
    probe = Path("/tmp/zovexbench.bin")

    print(f"🔬 קובץ מבחן {args.mb}MB · {len(counts)} מדידות")
    print(f"   ההגדרה היום: TG_CONNECTIONS={config.TG_CONNECTIONS}\n")

    # נתונים אקראיים, כדי שהדחיסה ברשת לא תזייף את התוצאה
    with probe.open("wb") as fh:
        left = size
        while left > 0:
            block = os.urandom(min(1 << 20, left))
            fh.write(block)
            left -= len(block)

    from telethon import TelegramClient
    from zovexsub import botapi
    session = (botapi._string_session(config.TG_STRING) if config.TG_STRING
               else config.TG_SESSION)
    client = TelegramClient(session, config.TG_API_ID, config.TG_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("❌ הסשן אינו מורשה.")
        probe.unlink(missing_ok=True)
        return 1

    print("  חיבורים   קצב        זמן")
    print("  " + "─" * 34)
    results: list[tuple[float, int]] = []
    try:
        for workers in counts:
            rate = await measure(client, probe, size, workers)
            results.append((rate, workers))
            mark = "  ← היום" if workers == config.TG_CONNECTIONS else ""
            spent = (args.mb / rate) if rate else 0
            print(f"  {workers:>7}   {rate:>6.1f}MB/s  {spent:>5.0f}ש{mark}",
                  flush=True)
            # הפוגה קצרה, כדי שמדידה אחת לא תשפיע על הבאה
            await asyncio.sleep(3)
    finally:
        await client.disconnect()
        probe.unlink(missing_ok=True)

    print("  " + "─" * 34)
    results = [r for r in results if r[0] > 0]
    if not results:
        print("\n❌ כל המדידות נכשלו.")
        return 1
    results.sort(reverse=True)
    best, workers = results[0]
    now = next((r for r, w in results if w == config.TG_CONNECTIONS), 0.0)

    print(f"\n🏆 הכי מהיר: {workers} חיבורים · {best:.1f}MB/s")
    if now and best > now * 1.15:
        print(f"   מהיר ב-{(best / now - 1) * 100:.0f}% מההגדרה היום "
              f"({now:.1f}MB/s).\n")
        print("   להחיל:")
        print(f"     sed -i '/^TG_CONNECTIONS=/d' /opt/zovexsub/bot/.env")
        print(f"     echo 'TG_CONNECTIONS={workers}' >> "
              f"/opt/zovexsub/bot/.env")
        print("     systemctl restart zovexsub")
    elif now:
        print(f"   ההגדרה היום ({now:.1f}MB/s) בתוך 15% מהטוב ביותר — "
              "אל תשנה.")
    # תקרה: אם התפוקה הפסיקה לעלות, הוספת חיבורים כבר לא עוזרת
    climbing = sorted(results, key=lambda r: r[1])
    if len(climbing) >= 2 and climbing[-1][0] < climbing[-2][0] * 1.05:
        print(f"\n   ⓘ התפוקה הפסיקה לעלות סביב {climbing[-2][1]} חיבורים — "
              "זו תקרת הרשת או תקרת טלגרם, לא שלנו.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
