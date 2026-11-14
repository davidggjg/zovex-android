"""יוצר מחרוזת סשן לחשבון משתמש. מריצים פעם אחת.

    cd /opt/zovexsub/repo/bot
    /opt/zovexsub/venv/bin/python tests/mksession.py

הכלי מבקש מספר טלפון, שולח אליו קוד, ומדפיס מחרוזת שנכנסת ל-.env.
מהרגע הזה החשבון עולה בלי התחברות ובלי קובץ session.

אזהרה: המחרוזת נותנת גישה מלאה לחשבון — כמו סיסמה. שומרים אותה ב-.env
בלבד, לא שולחים לאיש, ולא מכניסים לגיט. אם דלפה: בטלגרם, הגדרות ←
מכשירים ← ניתוק ההתקן, והמחרוזת מתבטלת.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from zovexsub import config
except ModuleNotFoundError as missing:
    print(f"חסרה הספרייה '{missing.name}'. הרץ עם הפייתון של הבוט:\n"
          f"    /opt/zovexsub/venv/bin/python tests/mksession.py")
    raise SystemExit(2)


async def main() -> int:
    if not config.TG_API_ID or not config.TG_API_HASH:
        print("חסרים TG_API_ID או TG_API_HASH ב-.env")
        return 2

    print("יצירת מחרוזת סשן לחשבון משתמש.")
    print("טלגרם ישלח קוד לאפליקציה של אותו חשבון.\n")

    # הסשן נוצר בזיכרון בלבד: אין קובץ שנשאר על הדיסק בטעות.
    # הקריאות אסינכרוניות — גרסה קודמת השתמשה ב-with רגיל, ואז
    # get_me החזיר coroutine והסקריפט קרס אחרי התחברות מוצלחת,
    # כלומר הקוד נשרף לחינם
    client = TelegramClient(StringSession(), config.TG_API_ID,
                            config.TG_API_HASH)
    await client.start()
    try:
        me = await client.get_me()
        value = client.session.save()
    finally:
        await client.disconnect()

    print("\n" + "=" * 60)
    print(f"מחובר כ: {me.first_name} (id={me.id})")
    print("=" * 60)
    print("\nהוסף ל-/opt/zovexsub/repo/bot/.env את השורה:\n")
    print(f"TG_STRING_LITE={value}\n")
    print("=" * 60)
    print("המחרוזת שווה לסיסמה של החשבון. אל תשלח אותה לאיש,")
    print("ואל תכניס אותה לגיט. לביטול: טלגרם ← הגדרות ← מכשירים.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
