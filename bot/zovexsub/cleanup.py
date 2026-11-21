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
    "\u10a0-\u10ff"  # גאורגית — נמצאה בתוך "ולנסיה" בקובץ אמיתי
    "\u0530-\u058f"  # ארמנית
    "\u0900-\u097f"  # דוואנגרי
    "\u0e00-\u0e7f"  # תאית
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
    עבריות באופן לגיטימי. אבל משפט באנגלית הוא לא שם. ראו english_line
    """
    return bool(FOREIGN.search(text)) or english_line(text)


# מילה לטינית של שלוש אותיות ומעלה. "OK" ו-"Bela" הן שמות; "laughing"
# או "door creaks" הן אנגלית, ומופיעות בשורות שהמודל השאיר כמו שהן
# כולל האותיות המורחבות (ş, ğ, ı, ü, é): בלעדיהן מילה טורקית נשברת
# לחתיכות קצרות ונראית כמו שם. נמדד: 384 שורות טורקיות חמקו כך
_LATIN_WORD = re.compile(r"[A-Za-z\u00c0-\u024f]{3,}")
_BRACKET = re.compile(r"\[([^\]]*)\]")


def untranslated(text: str) -> bool:
    """שורה שלא תורגמה כלל: אין בה עברית, ויש בה טקסט בשפה אחרת.

    שונה מאות זרה שנדבקה למילה עברית. שורה כזאת צריכה **תרגום**, ולא
    תיקון אותיות — ופרומפט התיקון אומר במפורש "אל תתרגם". נמדד בקובץ
    של סרט באנגלית שתורגם ממקור ערבי: 89 שורות ערביות שלמות שרדו,
    כי הן נשלחו לתיקון אותיות והמודל ציית
    """
    if not text or HEBREW.search(text):
        return False
    return bool(FOREIGN.search(text)) or bool(_LATIN_WORD.search(text))


def english_line(text: str) -> bool:
    """האם השורה היא אנגלית שלא תורגמה — ולא רק שם או מותג.

    נמדד בקובץ של הבוט עצמו: 259 מתוך 1664 כתוביות נשארו באנגלית,
    ו-249 מהן היו תיאורי צליל בסוגריים, כמו "[Mommy boops softly]".
    הבדיקה הישנה לא ראתה אותן בכלל, כי היא התעלמה מכל לטינית.

    הכלל: אם יש בשורה תיאור בסוגריים שמכיל מילה לטינית של שלוש אותיות
    ומעלה, או שיש בה שתי מילים כאלה לפחות — זו אנגלית. שם בודד או
    מותג בודד נשארים כמו שהם
    """
    if not text or not text.strip():
        return False
    for inside in _BRACKET.findall(text):
        if _LATIN_WORD.search(inside):
            return True
    return len(_LATIN_WORD.findall(text)) >= 2


def foreign_lines(lines: list[str]) -> list[int]:
    return [i for i, line in enumerate(lines) if line and has_foreign(line)]


# סימן סיום משפט שהמודל הניח בתחילת השורה. בעברית הוא שייך לסוף —
# "מה שלומך?" — ואם הוא בתחילה הוא נראה כאילו נדחף מהצד הלא נכון.
# נמדד אצל המשתמש: "?" בתחילת השורה. ‏מתקנים רק כשהשורה אכן עברית
# ורק אם הסימן ישב בתחילה ממש ואחריו מיד אות, כדי לא לגעת במקפי
# דו-שיח ("- תשמע") ובשלוש נקודות שפותחות שורה
_LEAD_MARK = re.compile(r"^\s*([?!.])\s*(?=[א-ת])")


def fix_leading_marks(line: str) -> str:
    """מעביר סימן סיום משפט מתחילת שורה עברית לסופה."""
    if not line or not HEBREW.search(line):
        return line
    match = _LEAD_MARK.match(line)
    if not match:
        return line
    rest = line[match.end():].rstrip()
    return f"{rest}{match.group(1)}"


# התטוויל הערבי (ـ) משמש בכתוביות ערביות כמקף דו-שיח, והמודל מעתיק
# אותו לעברית: "ـ עליך לפנות מזרחה. ـ מזרחה?" — 11 פעמים בקובץ אחד.
# זה תמיד מקף, ואין צורך במודל כדי להחליף אותו
_TATWEEL = re.compile(r"\u0640+")


def clean(lines: list[str]) -> tuple[list[str], list[int]]:
    """מנקה ניקוד ומחזיר גם את האינדקסים שעדיין מכילים אותיות זרות."""
    out = []
    for line in lines:
        cleaned = strip_niqqud(line or "")
        if HEBREW.search(cleaned):
            cleaned = _TATWEEL.sub("-", cleaned)
        if cleaned != line:
            log.info("הוסר ניקוד: %s", cleaned[:40])
        # האות הערבית מוחזרת כאן, לפני שמחליטים שהשורה "זרה". רוב
        # המקרים נפתרים כך בלי שום קריאה למודל, ומה שנשאר לתיקון
        # הוא באמת מה שאין לו מיפוי
        fixed = fix_leading_marks(mend_arabic(cleaned))
        if fixed != cleaned:
            log.info("סימן סיום הועבר לסוף השורה: %s", fixed[:40])
        out.append(fixed)
    return out, foreign_lines(out)
