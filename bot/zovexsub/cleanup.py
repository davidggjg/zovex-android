"""ניקוי טקסט עברי מארטיפקטים של מודלים.

שני דפוסים חוזרים: אותיות ערביות שנדחפות לתוך מילה עברית ("פתח" שיוצא
"פתح"), וניקוד שמשתרבב למילים בודדות. הראשון מזוהה כאן ונשלח לתיקון
ממוקד, השני מוסר ישירות.
"""
from __future__ import annotations

import logging
import re
import unicodedata

log = logging.getLogger(__name__)

# טעמים וניקוד עברי — אין להם מקום בכתוביות
NIQQUD = re.compile(r"[֑-ׇֽֿׁׂׅׄ]")
# אותיות ערביות, פרסיות וסוריות שאין להן מה לחפש בטקסט עברי
# ערבית, סורית, קירילית, יוונית, וכל ה-CJK — סינית, יפנית וקוריאנית.
# קודם היו כאן ערבית וסורית בלבד, ושורות שלמות בסינית עברו בשקט אל
# הקובץ הסופי. מתרגם מקצועי שבדק את הפלט מצא אותן לפנינו
FOREIGN = re.compile(
    "["
    "؀-ۿ"            # ערבית
    "ݐ-ݿ܀-ݏﭐ-﻿"   # סורית וצורות ערביות
    "Ѐ-ӿ"            # קירילית
    "Ͱ-Ͽ"            # יוונית
    "ぁ-ゟ゠-ヿ"      # יפנית
    "가-힣"           # קוריאנית
    "一-鿿㐀-䶿"      # סינית
    "]"
)
HEBREW = re.compile(r"[א-ת]")


def strip_niqqud(text: str) -> str:
    """מסיר ניקוד וטעמים, ומשאיר את האותיות עצמן."""
    return NIQQUD.sub("", unicodedata.normalize("NFC", text))


def has_foreign(text: str) -> bool:
    """האם יש כאן אות של שפה זרה שאינה אמורה להופיע בכתובית עברית.

    קודם נדרשה כאן גם עברית באותה שורה, והרעיון היה לתפוס אות בודדת
    שהשתרבבה. אבל זה החמיץ בדיוק את המקרה הגרוע: שורה שלא תורגמה
    כלל ונשארה שלמה בשפה זרה — אין בה עברית, ולכן היא עברה בשקט
    אל הקובץ הסופי. עכשיו כל אות זרה נספרת, עם או בלי עברית לידה.

    לטינית אינה כאן בכוונה: שמות, מותגים ו-OK מופיעים בכתוביות
    עבריות באופן לגיטימי
    """
    return bool(FOREIGN.search(text))


def foreign_lines(lines: list[str]) -> list[int]:
    return [i for i, line in enumerate(lines) if line and has_foreign(line)]


def clean(lines: list[str]) -> tuple[list[str], list[int]]:
    """מנקה ניקוד ומחזיר גם את האינדקסים שעדיין מכילים אותיות זרות."""
    out = []
    for line in lines:
        cleaned = strip_niqqud(line or "")
        if cleaned != line:
            log.info("הוסר ניקוד: %s", cleaned[:40])
        out.append(cleaned)
    return out, foreign_lines(out)
