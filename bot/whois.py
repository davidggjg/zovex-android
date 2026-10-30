"""מי שלח את ההודעה שהועברה לערוץ האחסון.

כלי חד-פעמי, לקריאה בלבד. המסירה מעבירה את ההודעה המקורית של השולח
(forwardMessage מהצ'אט הפרטי שלו), ולכן טלגרם שומרת על שדה ההעברה.
האפליקציה מציגה שם בלבד; כאן נקרא השדה הגולמי, שבו לפעמים יש גם
המזהה עצמו.

אם המשתמש הגדיר בפרטיות "הודעות שהועברו: לא לקשר לחשבון שלי",
השרת של טלגרם מוחק את from_id ומשאיר רק from_name — ואז המזהה
אינו קיים בשום מקום בצד שלנו.

שימוש:  python3 bot/whois.py 243
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zovexsub import botapi, config  # noqa: E402


async def main(message_id: int) -> int:
    if not config.TG_STRING:
        print("אין TG_STRING ב-.env — אין חשבון לקרוא איתו")
        return 1
    client = await botapi._connect(
        botapi._string_session(config.TG_STRING), label="בדיקה")
    if client is None:
        print("החשבון לא התחבר")
        return 1
    try:
        where = await botapi.storage(client)
        if where is None:
            print(f"ערוץ האחסון לא נפתר (STORAGE_CHAT={config.STORAGE_CHAT})")
            return 1
        message = await client.get_messages(where, ids=message_id)
        if message is None:
            print(f"הודעה {message_id} לא נמצאה בערוץ")
            return 1

        print(f"הודעה {message_id} · נשלחה {message.date}")
        forward = getattr(message, "fwd_from", None)
        if forward is None:
            print("אין שדה העברה — ההודעה לא הועברה, אלא נשלחה ישירות.")
            print("במצב כזה אין בה שום זכר לשולח המקורי.")
            return 0

        print("--- שדה ההעברה הגולמי ---")
        print(forward)
        origin = getattr(forward, "from_id", None)
        name = getattr(forward, "from_name", None)
        if origin is not None:
            who = getattr(origin, "user_id", None) or origin
            print(f"\n>>> המזהה: {who}")
            print(f">>> לחסימה: /deny {who}")
            try:
                user = await client.get_entity(origin)
                print(f">>> שם: {user.first_name} "
                      f"{getattr(user, 'last_name', '') or ''}".rstrip())
                if getattr(user, "username", None):
                    print(f">>> משתמש: @{user.username}")
            except Exception as exc:  # noqa: BLE001 — המזהה לבדו מספיק
                print(f"(לא הצלחתי לפתור את הפרופיל: {exc})")
        elif name:
            print(f"\n>>> יש שם בלבד: {name}")
            print(">>> המזהה נמחק על ידי טלגרם — הפרטיות של המשתמש מונעת")
            print(">>> את הקישור לחשבון. אין דרך לחלץ אותו מכאן.")
        else:
            print("\n>>> שדה ההעברה ריק משניהם.")
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(int(sys.argv[1]))))
