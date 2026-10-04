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
FOREIGN = re.compile(r"[؀-ۿݐ-ݿ܀-ݏﭐ-﻿]")
HEBREW = re.compile(r"[א-ת]")


def strip_niqqud(text: str) -> str:
    """מסיר ניקוד וטעמים, ומשאיר את האותיות עצמן."""
    return NIQQUD.sub("", unicodedata.normalize("NFC", text))


def has_foreign(text: str) -> bool:
    """האם יש כאן אות ערבית בתוך טקסט שהוא בעיקר עברי."""
    return bool(FOREIGN.search(text)) and bool(HEBREW.search(text))


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
