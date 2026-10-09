"""מודד מהירות הורדה מטלגרם בתצורות שונות, על החשבון והקו האמיתיים.

    systemctl stop zovexsub
    cd /opt/zovexsub/repo/bot
    /opt/zovexsub/venv/bin/python tests/dlbench.py
    systemctl start zovexsub

הכלי מסרב לרוץ בזמן שהבוט פעיל: חיבור שני לאותו חשבון משתק אותו.

שלח קודם קובץ גדול (300MB+) ל"הודעות שמורות" בטלגרם. הכלי מוריד ממנו
רק את ההתחלה בכל תצורה, מודד, ומדפיס טבלה.

למה זה קיים: כל תיאוריה על למה ההורדה איטית — מכסות, מקביליות, גודל
חלק, תקרת חשבון — נבדקת כאן במספרים במקום בוויכוח. התצורה שתנצח היא
זו שתיכנס ל-.env.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from telethon import TelegramClient, utils
    from telethon.errors import FloodWaitError
    from telethon.tl import functions, types
    from zovexsub import config, fastio
    from zovexsub.selftest import _bot_running
except ModuleNotFoundError as missing:
    print(f"חסרה הספרייה '{missing.name}'. הרץ עם הפייתון של הבוט:\n"
          f"    /opt/zovexsub/venv/bin/python bot/tests/dlbench.py")
    raise SystemExit(2)

# כמה להוריד בכל תצורה. מספיק כדי למדוד, קצר כדי לא לבזבז מכסה
BUDGET = 48 * 1024 * 1024

# (חיבורים, בקשות לחיבור, גודל חלק בקילו־בייט)
PLANS = [
    (1, 1, 512),     # הבסיס ההיסטורי
    (1, 4, 512),
    (4, 1, 512),
    (4, 4, 512),
    (4, 4, 1024),    # מה שרץ היום
    (8, 2, 1024),
    (2, 8, 1024),
]


async def measure(client, message, conns: int, pipe: int, part_kb: int) -> dict:
    part = part_kb * 1024
    dc_id, location = utils.get_input_location(message.media)
    dc_id = dc_id or client.session.dc_id
    total_parts = BUDGET // part
    queue: asyncio.Queue[int] = asyncio.Queue()
    for i in range(total_parts):
        queue.put_nowait(i)

    got = {"bytes": 0, "floods": 0, "premium": False, "errors": 0}
    senders = await fastio._open_senders(client, dc_id, conns)
    started = time.monotonic()

    async def pull(sender):
        while True:
            try:
                index = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                result = await asyncio.wait_for(
                    client._call(sender, functions.upload.GetFileRequest(
                        location, offset=index * part, limit=part)),
                    timeout=60)
            except FloodWaitError as flood:
                got["floods"] += 1
                if "PREMIUM" in str(type(flood).__name__).upper() or \
                   "PREMIUM" in str(getattr(flood, "message", "")).upper():
                    got["premium"] = True
                return
            except Exception:                       # noqa: BLE001
                got["errors"] += 1
                return
            if isinstance(result, types.upload.FileCdnRedirect):
                got["errors"] += 1
                return
            got["bytes"] += len(result.bytes)

    try:
        await asyncio.gather(*(pull(s) for s in senders
                               for _ in range(pipe)), return_exceptions=True)
    finally:
        await fastio._close_senders(senders)

    spent = max(0.001, time.monotonic() - started)
    return {"mbps": got["bytes"] / 1048576 / spent, "spent": spent, **got}


async def main() -> int:
    import shutil
    import tempfile

    origin = Path(f"{config.TG_SESSION}.session")
    if not origin.exists():
        print(f"אין קובץ session ב-{origin.resolve()}.\n"
              "הרץ מתוך /opt/zovexsub/repo/bot")
        return 2

    # חיבור שני לאותו חשבון — גם מעותק של ה-session — גורם לטלגרם
    # להפסיק להזרים עדכונים לבוט, והוא משתתק עד הפעלה מחדש. זה כבר
    # קרה בשרת הזה, ולכן הכלי מסרב לרוץ במקביל לבוט
    if _bot_running(origin):
        print("הבוט רץ. עצור אותו קודם, אחרת המדידה תשתק אותו:\n"
              "    systemctl stop zovexsub\n"
              "    /opt/zovexsub/venv/bin/python bot/tests/dlbench.py\n"
              "    systemctl start zovexsub")
        return 2

    work = Path(tempfile.mkdtemp(prefix="dlbench-"))
    session = work / "probe.session"
    shutil.copy2(origin, session)

    client = TelegramClient(str(session.with_suffix("")),
                            config.TG_API_ID, config.TG_API_HASH)
    await asyncio.wait_for(client.connect(), timeout=30)
    if not await client.is_user_authorized():
        print("הסשן אינו מחובר.")
        await client.disconnect()
        return 2

    message = None
    async for msg in client.iter_messages("me", limit=40):
        size = int(getattr(getattr(msg, "file", None), "size", 0) or 0)
        if size >= BUDGET:
            message = msg
            break
    if message is None:
        print(f"לא נמצא קובץ של לפחות {BUDGET // 1048576}MB ב'הודעות שמורות'.\n"
              "שלח לשם קובץ גדול ונסה שוב.")
        await client.disconnect()
        return 2

    print(f"קובץ מבחן: {message.file.size / 1048576:.0f}MB · "
          f"מודד {BUDGET // 1048576}MB בכל תצורה\n")
    print("חיבורים  בקשות  חלק     באוויר   קצב        הערות")
    best = None
    for conns, pipe, part_kb in PLANS:
        try:
            got = await measure(client, message, conns, pipe, part_kb)
        except Exception as exc:                    # noqa: BLE001
            print(f"   {conns:>2}      {pipe:>2}   {part_kb:>4}KB      —      נכשל: {exc}")
            continue
        notes = []
        if got["premium"]:
            notes.append("תקרת חשבון ללא Premium")
        elif got["floods"]:
            notes.append(f"{got['floods']} הגבלות קצב")
        if got["errors"]:
            notes.append(f"{got['errors']} שגיאות")
        print(f"   {conns:>2}      {pipe:>2}   {part_kb:>4}KB   {conns*pipe:>4}   "
              f"{got['mbps']:>6.2f} MB/s   {' · '.join(notes)}")
        if best is None or got["mbps"] > best[0]:
            best = (got["mbps"], conns, pipe, part_kb)
        await asyncio.sleep(3)      # נשימה בין תצורות

    await client.disconnect()
    if best:
        mbps, conns, pipe, part_kb = best
        print(f"\nהמהיר ביותר: {mbps:.2f} MB/s — {conns} חיבורים × {pipe} בקשות, "
              f"חלק {part_kb}KB")
        print("ל-.env:")
        print(f"  TG_CONNECTIONS={conns}")
        print(f"  TG_PIPELINE={pipe}")
        print(f"  TG_PART_MAX={part_kb * 1024}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
