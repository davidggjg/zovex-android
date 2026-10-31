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

# ערבית ועברית הן שתי אלפבתות שמיות עם אותן אותיות כמעט: lam הוא
# למד, ha הוא חית, mim הוא מם. המודל מחליף ביניהן בתוך מילה עברית,
# ולכן אפשר להחזיר את האות למקומה בלי לשאול אף מודל — מיידי, חינם
# וודאי. נמדד אצל המשתמש: "שתבلي" הוא "שתבלי", "תברحي" הוא
# "תברחי", "הم" הוא "הם"
ARABIC_TO_HEBREW = {
    "ا": "א", "أ": "א", "إ": "א", "آ": "א", "ء": "א", "ب": "ב",
    "ج": "ג", "د": "ד", "ذ": "ד", "ه": "ה", "ة": "ה", "و": "ו",
    "ز": "ז", "ح": "ח", "خ": "ח", "ط": "ט", "ظ": "צ", "ي": "י",
    "ى": "י", "ئ": "י", "ك": "כ", "ل": "ל", "م": "מ", "ن": "נ",
    "س": "ס", "ش": "ש", "ع": "ע", "غ": "ע", "ف": "פ", "ص": "צ",
    "ض": "צ", "ق": "ק", "ر": "ר", "ت": "ת", "ث": "ת",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
}
# אותיות סופיות: "הم" הוא "הם" ולא "המ"
FINALS = {"כ": "ך", "מ": "ם", "נ": "ן", "פ": "ף", "צ": "ץ"}
_ARABIC_MARKS = re.compile(r"[\u064b-\u0652\u0640]")


def mend_arabic(text: str) -> str:
    """מחזיר אות ערבית שהשתרבבה לאות העברית המקבילה לה.

    פועל רק במילה שיש בה גם עברית. שורה שכולה ערבית היא טקסט ערבי
    אמיתי ולא שיבוש, ואין להפוך אותה לג'יבריש עברי
    """
    if not FOREIGN.search(text):
        return text
    out = []
    for word in re.split(r"(\s+)", text):
        bare = _ARABIC_MARKS.sub("", word)
        letters = [c for c in bare if c in ARABIC_TO_HEBREW]
        if not letters or not HEBREW.search(bare):
            out.append(word)
            continue
        swapped = "".join(ARABIC_TO_HEBREW.get(c, c) for c in bare)
        # האות האחרונה של המילה עוברת לצורה הסופית
        trimmed = swapped.rstrip(".,!?:;\"')]}")
        tail = swapped[len(trimmed):]
        if trimmed and trimmed[-1] in FINALS:
            trimmed = trimmed[:-1] + FINALS[trimmed[-1]]
        out.append(trimmed + tail)
    mended = "".join(out)
    if mended != text:
        log.info("אות ערבית הוחזרה לעברית: %s ⇐ %s", mended[:50], text[:50])
    return mended


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
        # האות הערבית מוחזרת כאן, לפני שמחליטים שהשורה "זרה". רוב
        # המקרים נפתרים כך בלי שום קריאה למודל, ומה שנשאר לתיקון
        # הוא באמת מה שאין לו מיפוי
        out.append(mend_arabic(cleaned))
    return out, foreign_lines(out)
