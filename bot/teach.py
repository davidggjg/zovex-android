#!/usr/bin/env python3
"""לימוד מכתוביות אולפן שיושבות בתיקייה על השרת.

    /opt/zovexsub/venv/bin/python bot/teach.py /path/to/folder
    /opt/zovexsub/venv/bin/python bot/teach.py --shelf

מסלול שורת הפקודה. מהטלפון עדיף לשלוח את הקבצים לבוט עצמו, או
חבילת ZIP אחת — אותו מנוע בדיוק רץ בשני המקרים.
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zovexsub import learn, memory, studio   # noqa: E402


def _plain(text: str) -> str:
    """מנקה את תגיות ה-HTML של טלגרם מהדיווח, לקריאה בטרמינל."""
    return re.sub(r"</?[a-z]+>", "", text)


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(message)s")
    args = [a for a in sys.argv[1:] if a]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    if args[0] == "--shelf":
        print(f"ספרייה: {learn.shelf()}")
        print(f"זיכרון מובחר: {memory.stats()}")
        print(f"בנק סגנון: {len(studio.load_style())} קטעים")
        return 0

    folder = Path(args[0]).expanduser()
    if not folder.is_dir():
        print(f"אין תיקייה כזאת: {folder}")
        return 2

    report = learn.from_folder(folder)
    print()
    print(_plain(report.text()))
    print()
    print(f"ספרייה: {learn.shelf()} · זיכרון: {memory.stats()} · "
          f"סגנון: {len(studio.load_style())} קטעים")
    return 0 if report.learned else 1


if __name__ == "__main__":
    raise SystemExit(main())
