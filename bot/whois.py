"""מי שלח את ההודעה שהועברה לערוץ האחסון.

כלי חד-פעמי, לקריאה בלבד. המסירה מעבירה את ההודעה המקורית של השולח
(forwardMessage מהצ'אט הפרטי שלו), ולכן טלגרם שומרת על שדה ההעברה.
האפליקציה מציגה שם בלבד; כאן נקרא השדה הגולמי, שבו לפעמים יש גם
המזהה עצמו.

אם המשתמש הגדיר בפרטיות "הודעות שהועברו: לא לקשר לחשבון שלי",
השרת של טלגרם מוחק את from_id ומשאיר רק from_name — ואז המזהה
אינו קיים בשום מקום בצד שלנו.

שימוש:
  python3 bot/whois.py 243        הודעה אחת, בפירוט
  python3 bot/whois.py 230-250    סריקת טווח, לזהות איזו הודעה של מי
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zovexsub import botapi, config  # noqa: E402


def _label(message) -> str:
    """שם הקובץ בהודעה, כשיש."""
    document = getattr(getattr(message, "media", None), "document", None)
    for attribute in getattr(document, "attributes", ()) or ():
        name = getattr(attribute, "file_name", None)
        if name:
            return str(name)
    return "—"


async def scan(first: int, last: int) -> int:
    """סורק טווח הודעות ומראה מי שלח כל אחת ומה כתוב בכותרת ההעברה.

    ההודעה שמעניינת היא ההעברה שהבוט עשה מהצ'אט שלו עם הזר. היא
    מובדלת מהעלאות של החשבון עצמו בכך שהשולח שלה הוא הבוט
    """
    client = await botapi._connect(
        botapi._string_session(config.TG_STRING), label="בדיקה")
    if client is None:
        print("החשבון לא התחבר")
        return 1
    try:
        where = await botapi.storage(client)
        if where is None:
            print("ערוץ האחסון לא נפתר")
            return 1
        ids = list(range(first, last + 1))
        found = await client.get_messages(where, ids=ids)
        print(f"{'id':>5}  {'זמן':<20} {'שולח לערוץ':>14}  "
              f"{'מקור ההעברה':<22} קובץ")
        print("-" * 96)
        for message in found:
            if message is None:
                continue
            sender = getattr(message, "sender_id", None)
            forward = getattr(message, "fwd_from", None)
            origin = "—"
            if forward is not None:
                who = getattr(forward, "from_id", None)
                if who is not None:
                    origin = f"id={getattr(who, 'user_id', None) or who}"
                else:
                    origin = f"שם בלבד: {getattr(forward, 'from_name', '') or '?'}"
            when = message.date.strftime("%d/%m %H:%M:%S")
            print(f"{message.id:>5}  {when:<20} {str(sender):>14}  "
                  f"{origin:<22} {_label(message)[:40]}")
        print("\n‏id= פירושו שהמזהה קיים — זה מה שמחפשים.")
        print("'שם בלבד' פירושו שהפרטיות מחקה אותו.")
        return 0
    finally:
        await client.disconnect()


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
    args = sys.argv[1:]
    if len(args) == 1 and "-" in args[0]:
        begin, _, stop = args[0].partition("-")
        if begin.isdigit() and stop.isdigit():
            raise SystemExit(asyncio.run(scan(int(begin), int(stop))))
    if len(args) == 1 and args[0].isdigit():
        raise SystemExit(asyncio.run(main(int(args[0]))))
    print(__doc__)
    raise SystemExit(2)
