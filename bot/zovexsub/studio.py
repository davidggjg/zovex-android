"""לימוד מכתוביות אולפנים: קבצים מקצועיים שהבוט מתאמן עליהם.

שני שימושים שונים לגמרי, ולא כדאי לבלבל ביניהם — זה בדיוק מה שהמחקר
אומר:

**קובץ עברי + קובץ המקור של אותו סרט** → זוגות אמיתיים, כלומר זיכרון
תרגום. זה החזק. ההצמדה נעשית לפי **חפיפה בזמן** ולא לפי טקסט, וזו
השיטה המבוססת (Tiedemann, LREC 2008; וה-OpenSubtitles corpus בנוי
עליה). ההנחה: אותה שורה מופיעה על המסך בשני הקבצים באותו רגע בערך.
יתרונה המדויק על יישור טקסט הוא שהיא עומדת בהשמטות ובהוספות, שהן
בדיוק מה שמתרגמי אולפן עושים. הנוסחה שלו:
‏overlap = זמן משותף / (זמן משותף + זמן שאינו משותף), והסף 50%.

**קובץ עברי לבד** → *לא* זוגות. אין צד מקור, ואי אפשר ללמוד ממנו
מיפוי. מה שכן אפשר ללמוד ממנו זה **סגנון**, וזה נמדד: דוגמאות בשפת
המטרה לבד סוגרות כ-70% מהפער בין zero-shot ל-few-shot
(arXiv 2311.02310). אבל Zhang/Haddow/Birch (ICML 2023) מדדו שדוגמאות
אקראיות הן הגרוע מכל, ושצד-מטרה לבד נופל מזוגות אמיתיים — ולכן זה
נכנס למשבצת נפרדת בפרומפט, מסומן כסגנון ולא כתרגום לחיקוי, ונלקח
כקטע רצוף מתוך קובץ אחד ולא כשורות מפוזרות.

והשימוש השלישי, שאינו דורש מודל בכלל: **מדידה**. מתוך קבצי אולפן
אפשר למדוד את התקרות האמיתיות — אורך שורה, קצב קריאה, איך הם שוברים
שורה — במקום לקחת אותן ממסמכי נטפליקס. זה דטרמיניסטי ואפשר לבדוק אותו.
"""
from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path

from . import config, srt

log = logging.getLogger(__name__)

HEBREW = re.compile(r"[֐-׿]")
LATIN = re.compile(r"[A-Za-z]")

# הפרשי קצב קלאסיים בכתוביות: אותו סרט ב-23.976 מול 25 פריימים.
# בלי התיקון הזה קובץ נכון לגמרי נראה כאילו הוא נסחף, והחפיפה
# מתמוטטת לקראת סוף הסרט
SCALES = (1.0, 25.0 / 23.976, 23.976 / 25.0, 24.0 / 25.0, 25.0 / 24.0)
# חלון החיפוש של ההיסט. קבצים מהרשת נבדלים בדרך כלל בכמה שניות
# (פתיח של מפיץ), ולפעמים בדקה
OFFSET_WINDOW = 90.0
OFFSET_STEP = 0.25
# הסף של Tiedemann. מתחתיו ההצמדה היא ניחוש
OVERLAP_FLOOR = 0.5


def is_hebrew(text: str) -> bool:
    """האם הטקסט הזה עברי. לפי יחס ולא לפי נוכחות.

    שם לטיני בודד בתוך כתובית עברית אינו הופך אותה לאנגלית, וכתובית
    אנגלית עם מילה עברית אחת אינה עברית
    """
    heb = len(HEBREW.findall(text))
    lat = len(LATIN.findall(text))
    return heb > 0 and heb >= lat


def language_of(cues: list[srt.Cue]) -> str:
    """"he" כשרוב הקובץ עברי, "other" כשלא, "" כשאין טקסט."""
    texts = [(c.text or "") for c in cues if (c.text or "").strip()]
    if not texts:
        return ""
    hebrew = sum(1 for t in texts if is_hebrew(t))
    return "he" if hebrew * 2 > len(texts) else "other"


def _shift(cue: srt.Cue, scale: float, offset: float) -> tuple[float, float]:
    return cue.start * scale + offset, cue.end * scale + offset


def _overlap(one: tuple[float, float], two: tuple[float, float]) -> float:
    """הנוסחה של Tiedemann: משותף חלקי (משותף + שאינו משותף)."""
    common = min(one[1], two[1]) - max(one[0], two[0])
    if common <= 0:
        return 0.0
    union = max(one[1], two[1]) - min(one[0], two[0])
    return common / union if union > 0 else 0.0


def _score(source: list[srt.Cue], hebrew: list[srt.Cue],
           scale: float, offset: float) -> float:
    """סך החפיפה בהגדרה הזאת. משמש רק לבחירת ההיסט והקצב."""
    # הצד העברי הוא העוגן, ולכן עוברים עליו ומחפשים את המקור הקרוב
    spans = [_shift(c, scale, offset) for c in source]
    total = 0.0
    index = 0
    for cue in hebrew:
        here = (cue.start, cue.end)
        while index < len(spans) and spans[index][1] <= here[0]:
            index += 1
        look = index
        best = 0.0
        while look < len(spans) and spans[look][0] < here[1]:
            best = max(best, _overlap(here, spans[look]))
            look += 1
        total += best
    return total


def _length_fit(pairs: list[tuple[str, str]]) -> float:
    """מתאם בין אורך שורת המקור לאורך העברית שהוצמדה לה.

    זה שובר התיקו, והוא נחוץ. החפיפה בזמן לבדה **אינה מבדילה** בין
    ההצמדה הנכונה לבין הזזה של כתובית אחת שלמה: בקטע שבו הכתוביות
    יוצאות בקצב קבוע, שתיהן נותנות כמעט אותו ציון. נמדד כאן בבדיקה
    — ההצמדה יצאה מוסטת בכתובית אחת לכל אורך הקובץ, וכל זוג היה
    שגוי, בעוד הציון נראה מושלם.

    אורך הטקסט הוא אות עצמאי לגמרי: שורה ארוכה במקור מתורגמת לשורה
    ארוכה, ושורה בת מילה אחת לשורה בת מילה אחת. הזזה באחת מערבבת
    ארוכות עם קצרות ומפילה את המתאם, גם כשהזמנים נראים תקינים
    """
    if len(pairs) < 8:
        return 0.5
    xs = [float(len(a)) for a, _ in pairs]
    ys = [float(len(b)) for _, b in pairs]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    top = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    left = sum((x - mx) ** 2 for x in xs) ** 0.5
    right = sum((y - my) ** 2 for y in ys) ** 0.5
    if left <= 0 or right <= 0:
        return 0.5
    return max(0.0, top / (left * right))


def _pair_up(source: list[srt.Cue], hebrew: list[srt.Cue],
             scale: float, offset: float,
             floor: float) -> list[tuple[str, str]]:
    """ההצמדה עצמה בהגדרת זמן נתונה. ראו align."""
    spans = [_shift(c, scale, offset) for c in source]
    pairs: list[tuple[str, str]] = []
    index = 0
    for cue in hebrew:
        text = " ".join((cue.text or "").split())
        if not text:
            continue
        here = (cue.start, cue.end)
        while index < len(spans) and spans[index][1] <= here[0]:
            index += 1
        look = index
        taken = []
        while look < len(spans) and spans[look][0] < here[1]:
            if _overlap(here, spans[look]) >= floor:
                said = " ".join((source[look].text or "").split())
                if said:
                    taken.append(said)
            look += 1
        if taken:
            pairs.append((" ".join(taken), text))
    return pairs


def _peaks(scores: list[tuple[float, float]],
           apart: float, most: int) -> list[tuple[float, float]]:
    """השיאים המקומיים, מרוחקים זה מזה. ולמה לא פשוט הגבוהים ביותר:

    הגבוהים ביותר הם תמיד אותו שיא עצמו, בהפרש של רבע שנייה. כך כל
    רשימת המועמדות מתמלאת בהגדרה אחת, והמועמדת האמיתית השנייה —
    שהיא בדיוק מה שצריך להישקל מול הראשונה — נדחקת החוצה
    """
    out: list[tuple[float, float]] = []
    for score, offset in sorted(scores, key=lambda item: -item[0]):
        if any(abs(offset - taken) < apart for _, taken in out):
            continue
        out.append((score, offset))
        if len(out) >= most:
            break
    return out


def sync(source: list[srt.Cue], hebrew: list[srt.Cue],
         floor: float = OVERLAP_FLOOR) -> tuple[float, float]:
    """מוצא את הקצב וההיסט שמביאים את שני הקבצים לאותו ציר זמן.

    Tiedemann מסנכרן לפי שתי נקודות עיגון של מילים דומות. כאן אין
    מילים דומות — הצדדים בשפות שונות לגמרי — ולכן החיפוש ישיר: הקצב
    מתוך רשימה קצרה של הפרשי פריימים מוכרים, וההיסט בסריקה.

    הסריקה היא בצעד דק ובמעבר אחד, ולא גסה-ואז-מעודנת. נמדד כאן:
    בצעד של שנייה, ההגדרה הנכונה (היסט 7.3) נפלה על 7.0 וקיבלה 88%
    מהציון — פחות מהגדרה שגויה לגמרי שנפלה במדויק על השנייה. כלומר
    הסריקה הגסה סיננה את המנצחת האמיתית לפני שהיה מי שישקול אותה.

    ואז המועמדות נשקלות מחדש לפי אורכי הטקסט, כי החפיפה לבדה אינה
    מבדילה בין הצמדה נכונה להזזה בכתובית אחת. ראו _length_fit
    """
    if not source or not hebrew:
        return 1.0, 0.0
    # קובץ ענק בצעד דק הוא דקות. חצי שנייה עדיין קטן ממחצית משך
    # כתובית, ולכן אינו מפספס שיא
    step = OFFSET_STEP if len(hebrew) <= 1500 else OFFSET_STEP * 2
    best = (-1.0, 1.0, 0.0)
    for scale in SCALES:
        scores: list[tuple[float, float]] = []
        offset = -OFFSET_WINDOW
        while offset <= OFFSET_WINDOW:
            scores.append((_score(source, hebrew, scale, offset), offset))
            offset += step
        for score, at in _peaks(scores, apart=1.5, most=4):
            fit = _length_fit(_pair_up(source, hebrew, scale, at, floor))
            # ‫רוב המשקל לחפיפה, שהיא האות החזק. שובר התיקו מכריע רק
            # בין מועמדות שקרובות זו לזו בציון החפיפה
            weighted = score * (0.4 + 0.6 * fit)
            if weighted > best[0]:
                best = (weighted, scale, at)
    log.info("סנכרון: קצב %.4f, היסט %.2fש (ציון משוקלל %.1f)",
             best[1], best[2], best[0])
    return best[1], best[2]


def align(source: list[srt.Cue], hebrew: list[srt.Cue],
          floor: float = OVERLAP_FLOOR) -> list[tuple[str, str]]:
    """זוגות מקור→עברית מתוך שני קבצי כתוביות של אותו סרט.

    כל כתובית עברית מקבלת את כתוביות המקור שחופפות לה מעל הסף,
    ומחוברות לשורה אחת. כך השמטה או פיצול של המתרגם אינם מפילים את
    ההצמדה — וזה בדיוק היתרון של השיטה הזאת על יישור טקסט
    """
    if not source or not hebrew:
        return []
    scale, offset = sync(source, hebrew, floor)
    pairs = _pair_up(source, hebrew, scale, offset, floor)
    log.info("הוצמדו %d זוגות מתוך %d כתוביות עבריות (%.0f%%)",
             len(pairs), len(hebrew), 100 * len(pairs) / max(1, len(hebrew)))
    return pairs


def aligned_well(pairs: list[tuple[str, str]], hebrew_cues: int) -> bool:
    """האם ההצמדה הצליחה בכלל.

    ‏OpenSubtitles פוסל זוג קבצים שהניב יותר הצמדות ריקות מלא-ריקות,
    וזה המדד הנכון: שני קבצים של סרטים שונים ייצרו מעט מאוד הצמדות
    מעל הסף, ולזרוק אותם עדיף על להכניס זבל לזיכרון
    """
    return bool(hebrew_cues) and len(pairs) * 2 > hebrew_cues


# ───────── בנק הסגנון: עברית לבד ─────────
#
# לא זוגות, ולא מתאים לפי מילים — אין מה להתאים אליו. קטעים רצופים
# מקובץ אחד, כי בדיוק זה ההבדל בין "דוגמאות בתחום" (שסוגרות 70% מהפער)
# לבין "דוגמאות אקראיות" (שנמדדו כגרועות מאין דוגמאות בכלל)

STYLE_BLOCK = 12


def style_path() -> Path:
    return Path(config.MEMORY_PATH).parent / "style.jsonl"


def add_style(cues: list[srt.Cue], source: str = "") -> int:
    """שומר את הקובץ העברי כקטעים רצופים. מחזיר כמה קטעים נוספו."""
    texts = [" ".join((c.text or "").split()) for c in cues]
    texts = [t for t in texts if t]
    blocks = [texts[at:at + STYLE_BLOCK]
              for at in range(0, len(texts), STYLE_BLOCK)]
    blocks = [b for b in blocks if len(b) >= 4]
    if not blocks:
        return 0
    store = style_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("a", encoding="utf-8") as fh:
        for block in blocks:
            fh.write(json.dumps({"lines": block, "from": source},
                                ensure_ascii=False) + "\n")
    log.info("בנק הסגנון: נוספו %d קטעים מ-%s", len(blocks), source or "?")
    return len(blocks)


def load_style() -> list[dict]:
    store = style_path()
    if not store.exists():
        return []
    out = []
    for line in store.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("lines"):
            out.append(item)
    return out


def style_prompt(seed: int = 0) -> str:
    """קטע סגנון אחד לפרומפט, או מחרוזת ריקה.

    הקטע מתחלף בין חלונות (seed), כדי שהמודל לא יראה את אותן שתים-
    עשרה שורות שוב ושוב ויתחיל להחזיר אותן
    """
    bank = load_style()
    if not bank:
        return ""
    block = bank[seed % len(bank)] if seed else random.choice(bank)
    rows = "\n".join(block["lines"])
    return ("כך נראות כתוביות עברית של אולפן מקצועי. זו דוגמת **סגנון** "
            "בלבד — אורך שורה, משלב, פיסוק וצורות פנייה. התוכן שלה אינו "
            "קשור למה שאתה מתרגם, ואל תיקח ממנה מילים:\n"
            f"{rows}\n")


# ───────── מדידה: התקרות האמיתיות של האולפן ─────────


def profile(cues: list[srt.Cue]) -> dict:
    """מודד מקובץ אולפן את מה שאנחנו מגדירים בקונפיג כניחוש.

    אין כאן מודל ואין רשת — רק אריתמטיקה על הקובץ, ולכן אפשר לבדוק
    כל מספר כאן ביד
    """
    kept = [c for c in cues if (c.text or "").strip() and c.end > c.start]
    if not kept:
        return {}

    def median(values: list[float]) -> float:
        values = sorted(values)
        mid = len(values) // 2
        if not values:
            return 0.0
        if len(values) % 2:
            return values[mid]
        return (values[mid - 1] + values[mid]) / 2

    spans = [c.end - c.start for c in kept]
    flat = [" ".join((c.text or "").split()) for c in kept]
    rows = [[row for row in (c.text or "").splitlines() if row.strip()]
            for c in kept]
    cps = [len(t) / (c.end - c.start) for t, c in zip(flat, kept)]
    gaps = [b.start - a.end for a, b in zip(kept, kept[1:])
            if 0 <= b.start - a.end < 5]
    longest = [max((len(row) for row in group), default=0) for group in rows]

    return {
        "cues": len(kept),
        "span_median": round(median(spans), 2),
        "span_min": round(min(spans), 2),
        "span_max": round(max(spans), 2),
        "cps_median": round(median(cps), 1),
        # לא המקסימום, שהוא תמיד חריג בודד, אלא האחוזון ה-90:
        # התקרה שהאולפן באמת עובד מתחתיה
        "cps_p90": round(sorted(cps)[int(len(cps) * 0.9)], 1),
        "chars_median": int(median([float(len(t)) for t in flat])),
        "line_max": max(longest) if longest else 0,
        "line_p90": sorted(longest)[int(len(longest) * 0.9)] if longest else 0,
        "two_lines": round(100 * sum(1 for g in rows if len(g) > 1)
                           / len(rows)),
        "three_lines": sum(1 for g in rows if len(g) > 2),
        "gap_median": round(median(gaps), 3) if gaps else 0.0,
    }
