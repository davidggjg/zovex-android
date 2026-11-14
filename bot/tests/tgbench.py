"""ניסוי השוואתי מבוקר על מהירות ההורדה מטלגרם.

למה זה קיים: אחרי יום של שינויי פרמטרים, שני מחקרים נפרדים הגיעו
לאותה מסקנה — אין ראיה שמספר חיבורים גבוה יותר מביא מהירות גבוהה
יותר, אין ראיה ש-Premium מרים את התקרה ב-MTProto, ואין ראיה שכתובת
של דאטה־סנטר נחנקת. כל שינוי נוסף בלי מדידה הוא ניחוש.

הכלי מוריד את אותו קטע מאותו קובץ בכמה תצורות, ברצף, ומדפיס טבלה.
הוא מוריד רק את ההתחלה — מספיק כדי למדוד קצב יציב ובלי לשרוף מכסה.

שימוש:
    python3 tests/tgbench.py https://t.me/c/1234567890/42
    python3 tests/tgbench.py https://t.me/channel/42 --mb 150
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# (חיבורים, בקשות לחיבור, גודל חלק בבתים)
PLANS = [
    (1, 1, 512 * 1024),      # חיבור יחיד — קו הבסיס
    (4, 1, 512 * 1024),      # ברירת המחדל של tdl ושל הלקוח הרשמי
    (8, 1, 1024 * 1024),
    (16, 1, 1024 * 1024),    # מה שאנחנו מריצים היום
    (16, 1, 512 * 1024),     # אותו מספר חיבורים, חלק קטן יותר
    (24, 1, 1024 * 1024),
]


async def measure(client, message, want: int, plan, work: Path) -> dict:
    from zovexsub import config, fastio

    links, pipeline, part = plan
    config.TG_CONNECTIONS = links
    config.TG_PIPELINE = pipeline
    config.TG_INFLIGHT_MAX = links * pipeline
    config.TG_PART_MAX = part
    config.TG_BIG_PART_FROM = 1          # תמיד הגודל שביקשנו

    target = work / f"p{links}_{part // 1024}.bin"
    moved = {"bytes": 0}
    stop = asyncio.Event()

    async def on_progress(done, total, note=""):
        moved["bytes"] = done
        if done >= want:
            stop.set()

    began = time.monotonic()
    task = asyncio.ensure_future(fastio._parallel_download(
        client, message, target, want, links, on_progress))
    try:
        await asyncio.wait_for(stop.wait(), timeout=300)
    except asyncio.TimeoutError:
        pass
    elapsed = max(0.01, time.monotonic() - began)
    task.cancel()
    try:
        await task
    except BaseException:
        pass
    target.unlink(missing_ok=True)
    return {"links": links, "part": part,
            "mb": moved["bytes"] / 1048576,
            "rate": moved["bytes"] / 1048576 / elapsed,
            "secs": elapsed}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("link", help="קישור להודעה בטלגרם עם הקובץ")
    ap.add_argument("--mb", type=int, default=120,
                    help="כמה מגה־בייט למדוד בכל תצורה")
    ap.add_argument("--repeat", type=int, default=1,
                    help="כמה פעמים לחזור על כל תצורה")
    args = ap.parse_args()

    from telethon import TelegramClient

    from zovexsub import config

    bench = Path(tempfile.mkdtemp(prefix="tgbench-session-"))
    session = _session(config.TG_SESSION, bench)
    if session is None:
        print("לא נמצא קובץ סשן. חיפשתי בשמות האלה:")
        for path in _candidates(config.TG_SESSION):
            print(f"  {path}")
        print("הריצי את הכלי מתוך תיקיית העבודה של השירות, "
              "או העבירי TG_SESSION עם נתיב מלא.")
        return 2

    client = TelegramClient(str(session), config.TG_API_ID,
                            config.TG_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("הסשן אינו מחובר — הקובץ נמצא אבל אינו מאומת: "
              f"{session}")
        return 2

    me = await client.get_me()
    message = await client.get_messages(*_parse(args.link))
    if not message or not message.file:
        print("לא נמצא קובץ בהודעה הזאת")
        return 2

    size = message.file.size
    dc = getattr(message.file.media, "dc_id", "?")
    print(f"חשבון: {me.first_name} · Premium: "
          f"{'כן' if getattr(me, 'premium', False) else 'לא'}")
    print(f"קובץ: {size / 1048576:.0f}MB · DC {dc} · "
          f"מודדים {args.mb}MB בכל תצורה\n")

    want = min(args.mb * 1048576, size)
    work = Path(tempfile.mkdtemp(prefix="tgbench-"))
    rows = []
    try:
        for plan in PLANS:
            if plan[0] * plan[2] > want:
                continue
            runs = []
            for _ in range(args.repeat):
                runs.append(await measure(client, message, want, plan, work))
                await asyncio.sleep(3)
            rate = statistics.median(r["rate"] for r in runs)
            rows.append((plan, rate, runs[0]["mb"]))
            print(f"{plan[0]:>3} חיבורים · חלק {plan[2] // 1024:>4}KB  "
                  f"->  {rate:5.2f} MB/s   ({runs[0]['mb']:.0f}MB)")
    finally:
        shutil.rmtree(work, ignore_errors=True)
        await client.disconnect()
        shutil.rmtree(bench, ignore_errors=True)

    if rows:
        best = max(rows, key=lambda r: r[1])
        print(f"\nהמהיר ביותר: {best[0][0]} חיבורים, חלק "
              f"{best[0][2] // 1024}KB — {best[1]:.2f} MB/s")
        worst = min(rows, key=lambda r: r[1])
        if best[1] < worst[1] * 1.3:
            print("כל התצורות קרובות זו לזו — מספר החיבורים אינו "
                  "הגורם המגביל, והתקרה היא בצד של טלגרם.")
    return 0


def _candidates(name: str):
    """כל המקומות שבהם קובץ סשן בשם הזה יכול לשכון.

    השירות רץ מתוך WorkingDirectory משלו, ולכן שם יחסי כמו
    "zovexsub" מצביע על קובץ אחר כשמריצים את הכלי מתיקיית הריפו.
    """
    stem = Path(name)
    names = [stem, stem.with_suffix(".session")] if not stem.suffix \
        else [stem]
    if stem.is_absolute():
        return names
    roots = [Path.cwd(), Path(__file__).resolve().parent.parent,
             Path("/opt/zovexsub/bot"), Path("/opt/zovexsub"),
             Path.home()]
    seen, out = set(), []
    for root in roots:
        for leaf in names:
            path = root / leaf
            if path not in seen:
                seen.add(path)
                out.append(path)
    return out


def _session(name: str, work: Path):
    """מעתיק את קובץ הסשן לעותק פרטי ומחזיר את נתיבו.

    השירות הרץ מחזיק מנעול SQLite על הקובץ המקורי, ולכן פתיחה
    ישירה שלו תיכשל או תפריע לבוט. עותק פותר את שניהם.
    """
    for path in _candidates(name):
        if not path.is_file():
            continue
        copy = work / "bench.session"
        shutil.copy2(path, copy)
        for extra in ("-journal", "-wal", "-shm"):
            side = path.with_name(path.name + extra)
            if side.is_file():
                shutil.copy2(side, copy.with_name(copy.name + extra))
        print(f"סשן: {path} (עותק זמני)")
        return copy
    return None


def _parse(link: str):
    parts = [p for p in link.rstrip("/").split("/") if p]
    number = int(parts[-1])
    if "c" in parts and parts.index("c") == len(parts) - 3:
        return int("-100" + parts[-2]), number
    return parts[-2], number


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
