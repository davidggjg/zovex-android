"""הלב של המערכת: הפיכת תמליל גולמי לכתוביות עברית ברמת אולפן.

ארבעה מעברים:
  1. חקר (מחובר לחיפוש Google) — נושא, דוברים, מגדרים, שמות, מונחים, ציטוטים.
  2. תרגום/עריכה בחלונות, עם כל מסקנות החקר כקונטקסט.
  3. בדיקת עקביות על כל הטקסט — זכר/נקבה, יחיד/רבים, מונחים, שמות.
  4. תיקון ממוקד רק של השורות שהבדיקה סימנה.

ההפרדה הזו היא מה שפותר את הבעיה של זכר/נקבה: ההחלטה מי מדבר ואל מי
מתקבלת פעם אחת על כל הסרטון, ולא מחדש בכל שורה.
"""
from __future__ import annotations

import asyncio
import logging
import re

from . import cleanup, config, gemini
from .stt import Segment

log = logging.getLogger(__name__)

# שורות שמתורגמות בקריאה אחת. היה 35, וזה היה חלון צר מדי משתי בחינות:
# פרק של 1700 שורות דרש 49 קריאות לג'מיני — והמכסה, לא המעבד, היא מה
# שמעכב את כל השלב הזה — וגם המגדר נקבע על בסיס צר יותר. 50 מוריד ל-34
# קריאות ונותן למודל יותר שיחה לראות. שורה שחוזרת חסרה עדיין מתוקנת
# בקריאת תיקון נקודתית, כך שחלון גדול יותר אינו מסכן שלמות
WINDOW = 50          # שורות שמתורגמות בקריאה אחת
CONTEXT = 12         # שורות הקשר לפני ואחרי (לא מתורגמות שוב)

# חלוקת טווחי ההתקדמות. כל אחד מהמעברים האחרונים הוא קריאה אחת ארוכה
# על כל הטקסט, ולכן מקבל טווח משלו ולא כמה אחוזים בסוף
RESEARCH_TO = 0.15       # מסמך החקר
TRANSLATE_FROM = 0.15
TRANSLATE_TO = 0.65      # התרגום עצמו
ADDRESSEE_TO = 0.82      # התאמת מגדר הפנייה
QUALITY_TO = 0.95        # בקרת איכות וניקוי

PEOPLE_SYSTEM = """אתה עורך לשוני ראשי באולפן כתוביות מקצועי בישראל.
לפניך תמליל גולמי של סרטון. תפקידך למפות מי מדבר ואל מי — זה מה שקובע
את כל צורות הזכר והנקבה בתרגום, וזה החלק שמכריע אם הכתוביות נשמעות
נכון או שבורות. אל תחפש באינטרנט, הכל נמצא בתמליל עצמו."""

PEOPLE_USER = """להלן תמליל גולמי (שפת מקור: {language}).
כתוב מסמך הנחיות בעברית, בסעיפים הבאים בדיוק:

1. נושא והקשר: על מה הסרטון, סוג התוכן (שיעור / פודקאסט / חדשות / סרטון שיווקי / שיחה פרטית / הרצאה), ורמת המשלב הנדרשת בעברית.
2. דוברים: רשימת הדוברים שזוהו, ולכל אחד — מגדר (זכר/נקבה/לא ידוע) ועל מה הסתמכת (שם, פנייה אליו, צורות דקדוק במקור, הקשר).
3. נמענים: אל מי כל דובר פונה בכל חלק — יחיד זכר, יחידה נקבה, רבים מעורב, קהל. זה הסעיף הקריטי ביותר: ציין במפורש את מספרי השורות שבהם הפנייה מתחלפת (למשל "משורה 412 ואילך הוא פונה לאישה — צריך לשון נקבה").
4. אזהרות: כל דבר נוסף שמתרגם חייב לדעת.

בסוף המסמך, בשורה נפרדת ואחרונה, כתוב טבלת מגדר קומפקטית בפורמט הזה
בדיוק, בלי שום טקסט נוסף באותה שורה:
@מגדר: A=זכר, B=נקבה, C=לא ידוע
השתמש באותן אותיות דובר שמופיעות בתמליל. זו השורה שתוצמד לכל קטע
תרגום, ולכן היא חייבת להיות מדויקת וקצרה.

התמליל:
{transcript}
כשמופיע "(דובר A)" לפני שורה — זהו זיהוי אוטומטי של מי מדבר. זה נתון
עובדתי ולא ניחוש: כל השורות של אותו דובר יצאו מאותו אדם. השתמש בו כדי
לקבוע מגדר אחיד לכל דובר, ולזהות מי פונה אל מי בחילופי דברים.
"""

FACTS_SYSTEM = """אתה עורך לשוני באולפן כתוביות. לפניך קטע מתוך תמליל
גולמי. תפקידך לחלץ ממנו שמות, מונחים וציטוטים, ולאמת אותם בחיפוש
באינטרנט. דיוק עובדתי קודם לכל. אתה מקבל קטע אחד מתוך סרטון ארוך —
התייחס רק למה שמופיע בו, ואל תנסה לסכם את הסרטון כולו."""

FACTS_USER = """להלן קטע {part} מתוך {total} בתמליל (שפת מקור: {language}).
חלץ וכתוב בעברית, בסעיפים האלה בדיוק. סעיף בלי ממצאים — כתוב "אין".

שמות פרטיים: כל שם של אדם/מקום/חברה/מוצר שמופיע בקטע, והאיות הנכון בעברית. חפש באינטרנט כדי לאמת איות של שמות לא מוכרים.
מונחים: מונחים מקצועיים — מונח במקור ⇒ התרגום הקבוע שישמש בכל הסרטון.
ציטוטים ומקורות: פסוק, שיר, חוק, מחקר או נתון שמצוטט — אמת בחיפוש וכתוב את הנוסח המדויק.
שגיאות תמלול: מילים שנשמע שהתמלול שיבש, ומה הכוונה המקורית הסבירה.

הקטע:
{transcript}"""

# התמליל נחתך לקטעים שרצים במקביל. מעבר העובדות משתמש בחיפוש גוגל, וזה
# איטי — קריאה אחת על פרק שלם הייתה החלק הסדרתי היחיד בכל הצינור
FACTS_CHUNK = 30_000     # תווים לקריאה
FACTS_CHUNKS_MAX = 4


TRANSLATE_SYSTEM = """אתה מתרגם כתוביות בכיר באולפן ישראלי. אתה מפיק עברית
טבעית, מדויקת ומדוברת — כזו שצופה ישראלי לא מרגיש שתורגמה.

חוקי ברזל:
1. מגדר. זה הדבר החשוב ביותר. עברית מטה פעלים, שמות תואר, כינויים ומספרים
   לפי מגדר. לפני כל שורה החלט: מי הדובר (זכר/נקבה) ואל מי הוא פונה
   (אתה/את/אתם/אתן). השתמש במסמך ההנחיות שקיבלת ולא בניחוש.
   - פנייה ליחידה: "את יודעת", "שלך", "בואי", "תגידי" — לא "אתה יודע".
   - פנייה ליחיד: "אתה יודע", "בוא", "תגיד".
   - דוברת על עצמה: "אני הלכתי ואמרתי לו שאני עייפה" (לא "עייף").
   - קהל מעורב: לשון זכר רבים.
   - אם ההנחיות אומרות "לא ידוע": בחר את הצורה הנייטרלית ביותר, או נסח
     מחדש כדי להימנע מהכרעה מגדרית. אל תמציא מגדר.
2. עברית נכונה: סמיכות, יחס, מספרים (שלוש בנות / שלושה בנים), ו' החיבור,
   זמנים. בלי תרגום מילולי מאנגלית ובלי תחביר זר.
3. משלב: שמור על הטון של המקור. דיבור יומיומי נשאר יומיומי; הרצאה נשארת
   רשמית. קללה מתורגמת, לא מרוככת, אלא אם זה תוכן חינוכי.
4. כתוביות: שורה קצרה וקריאה. בלי "אמ", "אהה", גמגום וחזרות מיותרות.
   בלי שמות דוברים, בלי סוגריים מרובעים, בלי הערות שלך.
5. התאמה אחד-לאחד: לכל שורת מקור יוצאת שורת עברית אחת, באותו אינדקס.
   אם שורה במקור ריקה מתוכן — החזר מחרוזת ריקה. אסור לאחד או לפצל שורות.
6. אם המקור כבר בעברית: אל תתרגם — ערוך. תקן זכר/נקבה, פיסוק, שיבושי
   תמלול ומילים קטועות, ושמור על הניסוח המקורי.

מחזיר תמיד JSON בלבד.
כשמופיע "(דובר A)" לפני שורה — זהו זיהוי אוטומטי של מי מדבר. זה נתון
עובדתי ולא ניחוש: כל השורות של אותו דובר יצאו מאותו אדם. השתמש בו כדי
לקבוע מגדר אחיד לכל דובר, ולזהות מי פונה אל מי בחילופי דברים.
"""

CHECK_SYSTEM = """אתה בקרת איכות לשונית באולפן כתוביות. אתה מקבל כתוביות
בעברית ואת מסמך ההנחיות, ומאתר שגיאות. אתה לא משפר סגנון — אתה מוצא
שגיאות אמיתיות, ובראשן התאמת מגדר שגויה (פנייה בלשון זכר למי שהיא אישה
ולהפך), חוסר עקביות במונחים ובשמות, מספרים שלא מותאמים, ומשפטים שאיבדו
את המשמעות של המקור. מחזיר תמיד JSON בלבד."""


ADDRESSEE_SYSTEM = """אתה עורך כתוביות שתפקידו היחיד הוא התאמת מגדר הפנייה
בעברית. אתה מקבל את המקור ואת התרגום, ועובר שורה-שורה.

לכל שורה אתה קובע שני דברים:
  1. מי הדובר ומה המגדר שלו — משפיע על "אני עייף" מול "אני עייפה".
  2. אל מי הוא פונה — יחיד זכר, יחידה נקבה, רבים, או אף אחד (אמירה כללית).

העיקרון החשוב ביותר: **רצף**. כל עוד אותו דובר מדבר אל אותו אדם, הצורה
חייבת להישאר זהה לאורך כל הרצף. "אתה דורך" ואחריו "תראי" באותו מונולוג
הוא בהכרח שגיאה. החלפת נמען קורית רק כשמשהו במקור מעיד עליה.

דיאלוג מתחלף: בשיחה בין שניים, הנמען של שורה אחת הוא בדרך כלל הדובר של
השורה שלפניה.

אתה מתקן רק צורות פנייה ומגדר. אסור לשנות מילים, ניסוח, פיסוק או
משמעות. מחזיר תמיד JSON בלבד.
כשמופיע "(דובר A)" לפני שורה — זהו זיהוי אוטומטי של מי מדבר. זה נתון
עובדתי ולא ניחוש: כל השורות של אותו דובר יצאו מאותו אדם. השתמש בו כדי
לקבוע מגדר אחיד לכל דובר, ולזהות מי פונה אל מי בחילופי דברים.
"""


ADDRESSEE_WINDOW = 120   # שורות שנבדקות בקריאה אחת
ADDRESSEE_CONTEXT = 15   # שורות הקשר לפני ואחרי


async def enforce_addressee(segments: list[Segment], lines: list[str], notes: str,
                            on_step=None) -> list[str]:
    """קובע לכל שורה אל מי פונים ואוכף את הצורה המתאימה.

    מחולק לחלונות שרצים במקביל. קריאה אחת על פרק שלם הייתה צריכה להחזיר
    את כל השורות בחזרה — אלפי שורות פלט — וזה לקח דקות ארוכות וסיכן
    חריגה ממגבלת הפלט. כאן כל חלון מחזיר רק את מה שהוא שינה.
    """
    indexed = [i for i in range(len(segments)) if lines[i]]
    if not indexed:
        return lines

    schema = {
        "type": "object",
        "properties": {
            "fixes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "i": {"type": "integer"},
                        "addressee": {"type": "string"},
                        "he": {"type": "string"},
                    },
                    "required": ["i", "he"],
                },
            }
        },
        "required": ["fixes"],
    }

    starts = list(range(0, len(indexed), ADDRESSEE_WINDOW))
    workers = config.parallel(config.TRANSLATE_PARALLEL, config.GEMINI_API_KEYS)
    gate = asyncio.Semaphore(workers)
    changed = 0
    done = 0
    lock = asyncio.Lock()
    log.info("התאמת מגדר: %d חלונות, עד %d במקביל", len(starts), workers)

    def render(numbers: list[int]) -> str:
        return "\n".join(
            f"[{i}] מקור: {segments[i].text}\n[{i}] עברית: {lines[i]}" for i in numbers
        )

    async def one(start: int) -> None:
        nonlocal changed, done
        window = indexed[start:start + ADDRESSEE_WINDOW]
        before = indexed[max(0, start - ADDRESSEE_CONTEXT):start]
        after = indexed[start + ADDRESSEE_WINDOW:start + ADDRESSEE_WINDOW + ADDRESSEE_CONTEXT]

        genders = gender_table(notes)
        prompt = (f"מגדר הדוברים (מחייב): {genders}\n\n" if genders else "") + f"""מסמך הנחיות:
---
{_cap(notes, 12_000)}
---

הקשר קודם (לקריאה בלבד):
{render(before) or "(תחילת הסרטון)"}

הקשר הבא (לקריאה בלבד):
{render(after) or "(סוף הסרטון)"}

השורות לבדיקה:
{render(window)}

עבור עליהן לפי הסדר וקבע לכל אחת מי הדובר ואל מי הוא פונה. החזר **רק
את השורות שבהן הצורה לא תאמה את הנמען**, מתוקנות. שורה תקינה לא נכללת
בתשובה כלל. אם הכול תקין החזר מערך ריק.

החזר JSON: {{"fixes": [{{"i": <אינדקס>, "addressee": "יחיד/יחידה/רבים/אין",
"he": "<השורה המתוקנת>"}}]}}"""

        async with gate:
            try:
                result = await gemini.ask_json(ADDRESSEE_SYSTEM, prompt,
                                               schema=schema, temperature=0.0)
            except gemini.GeminiError as exc:
                log.warning("חלון התאמת מגדר נכשל: %s", exc)
                return

        items = result.get("fixes") if isinstance(result, dict) else result
        async with lock:
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                try:
                    index = int(item["i"])
                    text = str(item.get("he", "")).strip()
                except (KeyError, TypeError, ValueError):
                    continue
                if 0 <= index < len(lines) and text and text != lines[index]:
                    log.info("מגדר [%d] (%s): %s ⇐ %s", index,
                             item.get("addressee", "?"), text[:45], lines[index][:45])
                    lines[index] = text
                    changed += 1
            done += len(window)
            if on_step:
                await on_step(f"מתאים מגדר פנייה {done}/{len(indexed)}",
                              TRANSLATE_TO + (ADDRESSEE_TO - TRANSLATE_TO)
                              * done / max(1, len(indexed)))

    await asyncio.gather(*(one(start) for start in starts))
    log.info("מעבר הנמענים תיקן %d שורות", changed)
    return lines


REPAIR_SYSTEM = """אתה מתקן שגיאות כתיב בכתוביות בעברית. בשורות שאתה
מקבל השתרבבו אותיות של שפה אחרת, בדרך כלל ערבית, לתוך מילים עבריות —
למשל "פתח" שנכתב "פתح", או "לאחיך" שנכתב "לאחيك".

תפקידך: לכתוב כל שורה מחדש בעברית תקנית בלבד, תוך שמירה מוחלטת על
המשמעות, הניסוח והפיסוק. אל תתרגם מחדש, אל תשפר סגנון, אל תשנה מילים
שאינן פגומות. רק תקן את האותיות הזרות למה שהיה אמור להיכתב בעברית.

מחזיר תמיד JSON בלבד."""


async def repair_foreign(segments: list[Segment], lines: list[str],
                         indices: list[int]) -> list[str]:
    """מתקן שורות שבהן השתרבבו אותיות משפה אחרת."""
    if not indices:
        return lines

    log.warning("נמצאו %d שורות עם אותיות זרות — שולח לתיקון", len(indices))
    listing = "\n".join(
        f'[{i}] מקור: {segments[i].text}\n[{i}] פגום: {lines[i]}' for i in indices
    )
    schema = {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"i": {"type": "integer"}, "he": {"type": "string"}},
                    "required": ["i", "he"],
                },
            }
        },
        "required": ["lines"],
    }

    try:
        result = await gemini.ask_json(
            REPAIR_SYSTEM,
            f"{listing}\n\nהחזר JSON: {{\"lines\": [{{\"i\": <אינדקס>, "
            f"\"he\": \"<השורה בעברית תקנית>\"}}]}}",
            schema=schema, temperature=0.0,
        )
    except gemini.GeminiError as exc:
        log.warning("תיקון האותיות הזרות נכשל: %s", exc)
        return lines

    fixed = 0
    for item in (_collect(result) or {}).items():
        index, text = item
        if 0 <= index < len(lines) and text.strip() and not cleanup.has_foreign(text):
            log.info("תוקן [%d]: %s ⇐ %s", index, text[:40], lines[index][:40])
            lines[index] = text.strip()
            fixed += 1
    log.info("תוקנו %d שורות מתוך %d", fixed, len(indices))
    return lines


async def research_notes(numbered: str, language: str, on_step=None) -> str:
    """בונה את מסמך ההנחיות בכמה קריאות מקבילות במקום אחת סדרתית.

    קודם זו הייתה קריאה אחת על כל הפרק, עם חיפוש גוגל, ובלי שום דיווח
    התקדמות — החלק הסדרתי היחיד בצינור שכולו מקבילי, ובמקרה הרע שש
    דקות של שקט מוחלט לפני שהתרגום בכלל התחיל.

    עכשיו מיפוי הדוברים רץ בלי חיפוש (הוא לא צריך אותו, והחיפוש הוא מה
    שמאט), ובמקביל אליו חילוץ השמות והמונחים רץ מחולק לקטעים — כל קטע
    על מפתח אחר. הזמן הוא של הקריאה האיטית ביותר, לא של הסכום.
    """
    chunks = [numbered[i:i + FACTS_CHUNK]
              for i in range(0, min(len(numbered), FACTS_CHUNK * FACTS_CHUNKS_MAX),
                             FACTS_CHUNK)] or [numbered]

    done = 0
    total = len(chunks) + 1
    gate = asyncio.Lock()

    async def step(label: str) -> None:
        nonlocal done
        async with gate:
            done += 1
            if on_step:
                await on_step(f"חוקר את התוכן {done}/{total} · {label}",
                              RESEARCH_TO * done / total)

    async def people() -> str:
        text = await gemini.research(
            PEOPLE_SYSTEM,
            PEOPLE_USER.format(language=language, transcript=_cap(numbered, 120_000)),
            grounded=False,
        )
        await step("דוברים ונמענים")
        return text

    async def facts(index: int, chunk: str) -> str:
        text = await gemini.research(
            FACTS_SYSTEM,
            FACTS_USER.format(part=index + 1, total=len(chunks),
                              language=language, transcript=chunk),
        )
        await step("שמות ומונחים")
        return text

    if on_step:
        await on_step(f"חוקר את התוכן 0/{total}", 0.0)

    parts = await asyncio.gather(
        people(), *(facts(i, chunk) for i, chunk in enumerate(chunks))
    )

    who, *found = parts
    sections = [who.strip()] if who.strip() else []
    merged = "\n\n".join(part.strip() for part in found if part.strip())
    if merged:
        sections.append("שמות, מונחים וציטוטים שאותרו:\n" + merged)
    notes = "\n\n".join(sections)
    log.info("מסמך הנחיות נוצר: %d תווים מתוך %d קריאות", len(notes), total)
    return notes


async def build_hebrew(segments: list[Segment], language: str,
                       on_step=None) -> tuple[list[str], str]:
    """מחזיר את שורות העברית (באורך ובסדר של הסגמנטים) ואת מסמך ההנחיות."""
    numbered = "\n".join(f"[{s.index}] {s.text}" for s in segments)

    notes = await research_notes(numbered, language, on_step)
    if not notes:
        notes = "לא התקבל מסמך הנחיות. הסק מגדרים ונמענים מתוך הקונטקסט עצמו, בזהירות."

    lines = await _translate_all(segments, language, notes, on_step)
    if on_step:
        await on_step("מתאים מגדר פנייה", TRANSLATE_TO)
    lines = await enforce_addressee(segments, lines, notes, on_step)
    if on_step:
        await on_step("בודק איכות ועקביות", ADDRESSEE_TO)
    lines = await _quality_pass(segments, lines, notes, on_step)

    # ניקוי ארטיפקטים: ניקוד מוסר ישירות, אותיות זרות נשלחות לתיקון ממוקד
    lines, foreign = cleanup.clean(lines)
    if on_step:
        await on_step("מסיים", QUALITY_TO)
    if foreign:
        if on_step:
            await on_step("מתקן אותיות זרות", QUALITY_TO)
        lines = await repair_foreign(segments, lines, foreign)
        lines, _ = cleanup.clean(lines)

    return lines, notes


async def _translate_all(segments: list[Segment], language: str, notes: str,
                         on_step=None) -> list[str]:
    """מתרגם את כל החלונות במקביל.

    כל חלון עומד בפני עצמו: ההקשר שלו נלקח משורות המקור שלפניו ואחריו,
    ולא מתרגום של חלון קודם. לכן אין סיבה להריץ אותם בזה אחר זה, ומפתח
    לכל חלון מנצל את כל המפתחות במקום אחד.
    """
    out: list[str] = [""] * len(segments)
    schema = {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"i": {"type": "integer"}, "he": {"type": "string"}},
                    "required": ["i", "he"],
                },
            }
        },
        "required": ["lines"],
    }

    starts = list(range(0, len(segments), WINDOW))
    workers = config.parallel(config.TRANSLATE_PARALLEL, config.GEMINI_API_KEYS)
    gate = asyncio.Semaphore(workers)
    finished = 0
    log.info("מתרגם %d חלונות, עד %d במקביל", len(starts), workers)

    async def translate_window(start: int) -> None:
        nonlocal finished
        window = segments[start:start + WINDOW]
        before = segments[max(0, start - CONTEXT):start]
        after = segments[start + WINDOW:start + WINDOW + CONTEXT]

        genders = gender_table(notes)
        pinned = f"מגדר הדוברים (מחייב): {genders}\n\n" if genders else ""

        prompt = f"""{pinned}מסמך הנחיות לסרטון הזה:
---
{_cap(notes, 20_000)}
---

שפת המקור: {language}

הקשר קודם (לקריאה בלבד, אל תתרגם):
{_numbered(before) or "(תחילת הסרטון)"}

הקשר הבא (לקריאה בלבד, אל תתרגם):
{_numbered(after) or "(סוף הסרטון)"}

תרגם לעברית את השורות הבאות בלבד, לפי האינדקסים שלהן:
{_numbered(window)}

החזר JSON: {{"lines": [{{"i": <אינדקס>, "he": "<עברית>"}}, ...]}}
חובה להחזיר בדיוק {len(window)} פריטים, אינדקס לכל שורה שביקשתי."""

        async with gate:
            result = await gemini.ask_json(TRANSLATE_SYSTEM, prompt, schema=schema)
        got = _collect(result)
        for seg in window:
            out[seg.index] = (got.get(seg.index) or "").strip()

        missing = [s.index for s in window if not out[s.index]]
        for idx in missing:
            seg = segments[idx]
            async with gate:
                retry = await gemini.ask_json(
                    TRANSLATE_SYSTEM,
                    f"מסמך הנחיות:\n{_cap(notes, 8000)}\n\n"
                    f"תרגם לעברית שורת כתובית אחת (שפת מקור {language}). "
                    f'הקשר: "{_window_text(segments, idx)}"\n'
                    f'השורה לתרגום: "{seg.text}"\n'
                    'החזר JSON: {"lines":[{"i":%d,"he":"..."}]}' % idx,
                    schema=schema, temperature=0.3,
                )
            out[idx] = (_collect(retry).get(idx) or seg.text).strip()

        finished += len(window)
        log.info("תורגמו %d/%d שורות", finished, len(segments))
        if on_step:
            # הטווחים מחולקים לפי הזמן שכל שלב באמת לוקח, ולא לפי כמות
            # העבודה. מעבר שהוא קריאה אחת ארוכה צריך טווח משלו, אחרת
            # המד נראה תקוע בדיוק כשהוא עובד
            await on_step(f"מתרגם {finished}/{len(segments)} שורות",
                          TRANSLATE_FROM + (TRANSLATE_TO - TRANSLATE_FROM)
                          * finished / max(1, len(segments)))

    await asyncio.gather(*(translate_window(start) for start in starts))
    return out


# שורות בכל קריאת בקרת איכות. קודם זו הייתה קריאה אחת על כל הכתוביות
# (עד 200,000 תווים): מפתח אחד עבד בזמן שכל השאר עמדו פנויים, והשלב כולו
# היה חסום על הקריאה האיטית הזאת. חלונות מקביליים מנצלים את כל המפתחות,
# ובונוס: חלון קצר מקבל תשומת לב טובה יותר מהמודל מאשר ערימה ענקית
QUALITY_WINDOW = 120

_QUALITY_SCHEMA = {
    "type": "object",
    "properties": {
        "fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "he": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["i", "he"],
            },
        }
    },
    "required": ["fixes"],
}


def _quality_prompt(notes: str, paired: str) -> str:
    if not paired.strip():
        return ""
    genders = gender_table(notes)
    pinned = f"מגדר הדוברים (מחייב): {genders}\n\n" if genders else ""
    return pinned + f"""מסמך הנחיות:
---
{_cap(notes, 20_000)}
---

הכתוביות המלאות (מקור מול עברית):
{_cap(paired, 200_000)}

אתר רק שגיאות אמיתיות. סדר הבדיקה:

א. **עקביות הפנייה לאורך רצף**: עבור על השורות ברצף וזהה קטעים שבהם אותו
   דובר פונה לאותו אדם. בתוך קטע כזה חייבת להיות צורה אחת בלבד —
   או הכל "אתה/תגיד/שלך", או הכל "את/תגידי/שלך". כל מעבר באמצע הוא שגיאה,
   אלא אם מסמך ההנחיות אומר במפורש שהנמען התחלף שם. דוגמה לשגיאה:
   "אתה מוחץ ומוחץ" ואחריה "ואז פתאום את רואה" — אותו מונולוג, שתי צורות.
   הכרע לפי מסמך ההנחיות ולפי רוב הקטע, ותקן את כל השורות החורגות.
ב. דובר שמדבר על עצמו — התאמה למגדר שלו ("אני עייפה" מול "אני עייף").
ג. **מילים שגויות**: מילה שאינה קיימת בעברית, או קיימת אך לא מתאימה
   להקשר ונראית כמו בחירה שגויה של שורש דומה. דוגמה אמיתית: "נותרה נכה"
   תורגם בטעות ל"נכתשה". בדוק כל מילה חריגה מול המקור.
ד. עקביות מונחים ושמות לאורך כל הסרטון.
ה. מספרים מותאמים (שלוש בנות / שלושה בנים).
ו. ניסוח מסורבל שנשמע כמו תרגום מילולי. דוגמה: "מעדיף את הצד של
   הפלילים" במקום "נוטה לגנבה". תקן לעברית טבעית בלי לשנות משמעות.
ז. משמעות שאבדה מול המקור.

לכל שגיאה החזר את השורה המתוקנת במלואה.
אם אין שגיאות החזר מערך ריק. אל תשנה שורות תקינות ואל תשפר סגנון.
החזר JSON: {{"fixes": [{{"i": <אינדקס>, "he": "<עברית מתוקנת>", "why": "<הסיבה>"}}]}}"""


async def _quality_pass(segments: list[Segment], lines: list[str], notes: str,
                        on_step=None) -> list[str]:
    """סריקת איכות בחלונות מקביליים, ואחריה תיקון ממוקד."""
    starts = list(range(0, len(segments), QUALITY_WINDOW))
    done = 0
    lock = asyncio.Lock()

    async def one(start: int) -> list:
        nonlocal done
        stop = min(start + QUALITY_WINDOW, len(segments))
        paired = "\n".join(
            f"[{i}] מקור: {segments[i].text}\n[{i}] עברית: {lines[i]}"
            for i in range(start, stop) if lines[i]
        )
        prompt = _quality_prompt(notes, paired)
        if not prompt:
            return []
        try:
            result = await gemini.ask_json(CHECK_SYSTEM, prompt,
                                           schema=_QUALITY_SCHEMA, temperature=0.0)
        except gemini.GeminiError as exc:
            # חלון שנכשל לא מפיל את השאר. קודם כשל יחיד החזיר את כל
            # התרגום בלי שום בדיקת איכות
            log.warning("חלון בקרת איכות נכשל ומדולג: %s", exc)
            return []
        async with lock:
            done += 1
            if on_step:
                await on_step(f"בודק איכות {done}/{len(starts)}",
                              ADDRESSEE_TO + (1.0 - ADDRESSEE_TO)
                              * done / max(1, len(starts)))
        return (result.get("fixes") or []) if isinstance(result, dict) else []

    batches = await asyncio.gather(*(one(s) for s in starts))
    applied = 0
    for fix in (f for batch in batches for f in batch):
        try:
            idx = int(fix["i"])
            text = str(fix["he"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < len(lines) and text and text != lines[idx]:
            log.info("תיקון [%d]: %s", idx, str(fix.get("why", ""))[:120])
            lines[idx] = text
            applied += 1
    log.info("בדיקת האיכות רצה ב-%d חלונות ותיקנה %d שורות", len(starts), applied)
    return lines


def _collect(result: object) -> dict[int, str]:
    items = result.get("lines") if isinstance(result, dict) else result
    got: dict[int, str] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            got[int(item["i"])] = str(item.get("he", ""))
        except (KeyError, TypeError, ValueError):
            continue
    return got


def _numbered(segs: list[Segment]) -> str:
    """ממספר את השורות, ומסמן מי דיבר כשהתמלול יודע.

    זה הנתון היקר ביותר למגדר. בלעדיו המודל מנחש מי מדבר אל מי מתוך
    הטקסט בלבד, וזו בדיוק הנקודה שבה הזכר והנקבה נשברים. עם תווית דובר
    הוא יודע ששורה 12 ושורה 40 יצאו מאותו אדם.
    """
    rows = []
    for segment in segs:
        speaker = getattr(segment, "speaker", "")
        label = f" (דובר {speaker})" if speaker else ""
        rows.append(f"[{segment.index}]{label} {segment.text}")
    return "\n".join(rows)


def _window_text(segments: list[Segment], idx: int) -> str:
    lo, hi = max(0, idx - 3), min(len(segments), idx + 4)
    return " ".join(s.text for s in segments[lo:hi])


_GENDER_LINE = re.compile(r"^@מגדר:\s*(.+)$", re.MULTILINE)


def gender_table(notes: str) -> str:
    """מחלץ את שורת המגדר ממסמך החקר.

    סעיף 6: המסמך כבר נשאל על מגדר הדוברים, אבל ענה בפרוזה בתוך 20,000
    תווים. בכל חלון תרגום המודל נדרש לחלץ אותה מחדש מתוך ההקשר הארוך,
    וזה בדיוק המקום שבו המגדר מתהפך באמצע שיחה. שורה אחת קצרה שנעוצה
    בראש כל חלון עולה אפס קריאות ואינה משאירה מקום לפרשנות.
    """
    found = _GENDER_LINE.search(notes or "")
    if not found:
        return ""
    row = " ".join(found.group(1).split())[:300]
    return row


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…[נחתך]"
