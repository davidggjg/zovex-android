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
import time

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

בסוף המסמך כתוב **שתי שורות** נפרדות, בפורמט הזה בדיוק ובלי שום
טקסט נוסף בשורה. שתיהן יוצמדו לכל קטע תרגום.

@מגדר: A=זכר, B=נקבה, C=לא ידוע
לפי אותיות הדובר שבתמליל. אם אין בתמליל אותיות דובר — כתוב
"@מגדר: אין".

@דמויות: שם=מגדר, שם=מגדר
מגדר של כל דמות **לפי שמה**, ולא לפי אות דובר. זו השורה החשובה
ביותר: היא עובדת גם כשאין זיהוי דוברים, והיא מה שקובע אם פונים
לדמות ב"את" או ב"אתה". אם ידוע לך שם הסרטון — בסס אותה על רשימת
הדמויות והשחקנים שחיפשת ברשת, ולא על ניחוש מהתמליל. כלול כל
דמות שמדברת או שפונים אליה, גם כשהשם נזכר פעם אחת.

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

# שם הסרטון הוא הנתון היחיד שאינו מגיע מהתמלול עצמו, ולכן הוא
# היחיד שיכול לתקן אותו. בלעדיו החקר מחלץ שם מהתמליל, מחפש אותו
# ברשת ומאמת אותו — גם כשהתמלול שגה בו מלכתחילה. נמדד אצל
# המשתמש: הגיבורה Airi יצאה "היידי" בשישה מתוך תשעה אזכורים,
# והאימות ברשת לא יכול היה לעזור כי הוא חיפש "היידי"
FACTS_TITLE = """שם הסרטון: {title}
חפש ברשת את רשימת הדמויות והשחקנים של הסרטון הזה, וקבע לפיה את
איות השמות. שם שנשמע בתמליל אחרת מהשם ברשימה הרשמית — השם הרשמי
גובר, והתמלול שגה בו. ציין במפורש "בתמליל נשמע X, השם הנכון Y".
"""

FACTS_USER = """{titled}להלן קטע {part} מתוך {total} בתמליל (שפת מקור: {language}).
חלץ וכתוב בעברית, בסעיפים האלה בדיוק. סעיף בלי ממצאים — כתוב "אין".

שמות פרטיים: כל שם של אדם/מקום/חברה/מוצר שמופיע בקטע, והאיות הסביר בעברית. סמן ב-(?) שם שאינך בטוח באיותו.
מונחים: מונחים מקצועיים — מונח במקור ⇒ התרגום הקבוע שישמש בכל הסרטון.
ציטוטים ומקורות: פסוק, שיר, חוק, מחקר או נתון שמצוטט — ציין במה מדובר. סמן ב-(?) אם אינך בטוח.
שגיאות תמלול: מילים שנשמע שהתמלול שיבש, ומה הכוונה המקורית הסבירה.

הקטע:
{transcript}"""

# חילוץ ואימות הופרדו. קודם כל קריאת עובדות חיפשה בגוגל תוך כדי שהיא
# מעכלת 30,000 תווים של תמליל, וארבע כאלה במקביל לקחו דקות. אבל מה
# שבאמת צריך אימות הוא רשימת השמות — כמה מאות תווים — ולא התמליל.
# עכשיו החילוץ מהיר ובלי רשת, ואחריו קריאת אימות אחת וקטנה שרצה רק אם
# נשאר בה צורך
FACTS_CHUNK = 30_000     # תווים לקריאה
FACTS_CHUNKS_MAX = 4


VERIFY_SYSTEM = """אתה בודק עובדות באולפן כתוביות. לפניך רשימת שמות
ומונחים שחולצו מתמליל. אמת באינטרנט רק את מה שמסומן ב-(?) — השאר כבר
ודאי. תשובה קצרה: שורה לשם, בלי הסברים."""

VERIFY_USER = """אמת את האיות העברי של הפריטים המסומנים ב-(?).
החזר שורה לכל תיקון בפורמט: מקור ⇒ עברית
פריט שאין לגביו ממצא — דלג עליו.

{items}"""

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
        prompt = pinned_genders(notes) + f"""מסמך הנחיות:
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

        async def skip(why: str) -> None:
            """חלון שלא חזר נספר כמו חלון שחזר.

            קודם כשל החזיר return בלי לקדם את המונה, ולכן האחוזים
            נתקעו מתחת ל-100 לנצח — נמדד אצל המשתמש: "99% · בודק
            איכות 14/15 · אין תזוזה 10:26" על שלב שלמעשה הסתיים.
            דיווח שמשקר בדיוק ברגע שצריך אותו גרוע מאין דיווח
            """
            nonlocal done
            log.warning("חלון התאמת מגדר נכשל: %s", why)
            async with lock:
                done += len(window)
                if on_step:
                    await on_step(f"מתאים מגדר פנייה {done}/{len(indexed)}",
                                  TRANSLATE_TO + (ADDRESSEE_TO - TRANSLATE_TO)
                                  * done / max(1, len(indexed)))

        async with gate:
            try:
                # תקרה לחלון בודד. asyncio.gather ממתין לאיטי שבהם,
                # ולכן חלון אחד שנתקע בלופ של נסיונות מחזיק את כל
                # השלב: נמדד אצל המשתמש 23 קריאות ו-1430 שניות המתנה
                # למודל על שלב שארך 1159 שניות — כלומר 1.2 קריאות
                # באוויר בממוצע מתוך שמונה שהגייט מרשה. לא המפתחות
                # היו הצוואר ולא המכסות (429 היה אפס), אלא הגרורים
                result = await asyncio.wait_for(
                    gemini.ask_json(ADDRESSEE_SYSTEM, prompt,
                                    schema=schema, temperature=0.0,
                                    model=config.ADDRESSEE_MODEL or None,
                                    thinking=config.ADDRESSEE_THINKING),
                    timeout=config.ADDRESSEE_TIMEOUT)
            except (gemini.GeminiError, asyncio.TimeoutError) as first:
                # מעבר המגדר הוא התיקון הנראה ביותר בעברית, ולכן הוא
                # מקבל ניסיון שני ותקרה משלו. נמדד על אותו סרט לפני
                # ואחרי שהוספתי כאן תקרה אחידה: צורות זכר קפצו מ-14
                # ל-51 בעוד שתי הדמויות נשים — חלונות שדולגו פשוט
                # נשארו בלי תיקון מגדר
                log.warning("חלון התאמת מגדר נכשל (%s) — ניסיון שני",
                            type(first).__name__)
                try:
                    result = await asyncio.wait_for(
                        gemini.ask_json(ADDRESSEE_SYSTEM, prompt,
                                        schema=schema, temperature=0.0,
                                        model=config.ADDRESSEE_MODEL or None,
                                        thinking=config.ADDRESSEE_THINKING),
                        timeout=config.ADDRESSEE_TIMEOUT)
                except (gemini.GeminiError, asyncio.TimeoutError) as again:
                    await skip(f"{type(again).__name__} פעמיים")
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
                         indices: list[int], on_step=None) -> list[str]:
    """מתקן שורות שבהן השתרבבו אותיות משפה אחרת.

    עם תקרת זמן, ובכוונה. פסק הזמן הפנימי של ג'ימיני הוא 300 שניות
    לניסיון והוא מנסה על פני כמה מפתחות, כך שהשלב הזה יכול לרוץ רבע
    שעה בלי אף שורת לוג ובלי שהמסך יזוז — נמדד בשרת כעשר דקות על
    "מתקן אותיות זרות". וזה לא שווה את זה: הכתוביות כבר מוכנות, ומה
    שעומד על הפרק הוא כמה שורות בודדות עם אותיות לטיניות. עדיף סרט
    עם שלוש שורות פגומות מאשר עוד רבע שעה המתנה
    """
    if not indices:
        return lines
    # תקרה אפסית אינה "בלי הגבלה" אלא ביטול מוחלט: wait_for נכשל
    # מיד, והשלב נרשם בלוג כאילו ניסה. נמדד אצל המשתמש, שב-.env
    # שלו REPAIR_TIMEOUT=0 — ולכן אותיות ערביות שרדו לקובץ הסופי
    # בעוד הלוג אמר "עבר 0 שניות, ממשיכים בלעדיו"
    if config.REPAIR_TIMEOUT <= 0:
        log.warning("תיקון האותיות הזרות מבוטל (REPAIR_TIMEOUT=0) — "
                    "%d שורות נשארות כמו שהן", len(indices))
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

    began = time.monotonic()

    async def tick() -> None:
        """שהמסך יזוז. בלי זה השלב נראה מת בדיוק כשהוא עובד."""
        while on_step:
            await asyncio.sleep(5)
            waited = int(time.monotonic() - began)
            await on_step(f"מתקן {len(indices)} שורות · {waited}ש "
                          f"מתוך {config.REPAIR_TIMEOUT:.0f}", QUALITY_TO)

    pulse = asyncio.create_task(tick())
    try:
        result = await asyncio.wait_for(gemini.ask_json(
            REPAIR_SYSTEM,
            f"{listing}\n\nהחזר JSON: {{\"lines\": [{{\"i\": <אינדקס>, "
            f"\"he\": \"<השורה בעברית תקנית>\"}}]}}",
            schema=schema, temperature=0.0,
        ), timeout=config.REPAIR_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("תיקון האותיות הזרות עבר %.0f שניות — ממשיכים בלעדיו "
                    "(%d שורות נשארות כמו שהן)",
                    config.REPAIR_TIMEOUT, len(indices))
        return lines
    except gemini.GeminiError as exc:
        log.warning("תיקון האותיות הזרות נכשל: %s", exc)
        return lines
    finally:
        pulse.cancel()

    fixed = 0
    for item in (_collect(result) or {}).items():
        index, text = item
        if 0 <= index < len(lines) and text.strip() and not cleanup.has_foreign(text):
            log.info("תוקן [%d]: %s ⇐ %s", index, text[:40], lines[index][:40])
            lines[index] = text.strip()
            fixed += 1
    log.info("תוקנו %d שורות מתוך %d", fixed, len(indices))
    return lines


async def research_notes(numbered: str, language: str, on_step=None,
                         title: str = "") -> str:
    """בונה את מסמך ההנחיות בכמה קריאות מקבילות במקום אחת סדרתית.

    קודם זו הייתה קריאה אחת על כל הפרק, עם חיפוש גוגל, ובלי שום דיווח
    התקדמות — החלק הסדרתי היחיד בצינור שכולו מקבילי, ובמקרה הרע שש
    דקות של שקט מוחלט לפני שהתרגום בכלל התחיל.

    עכשיו מיפוי הדוברים רץ בלי חיפוש (הוא לא צריך אותו, והחיפוש הוא מה
    שמאט), ובמקביל אליו חילוץ השמות והמונחים רץ מחולק לקטעים — כל קטע
    על מפתח אחר. הזמן הוא של הקריאה האיטית ביותר, לא של הסכום.
    """
    # חילוץ השמות והמונחים קיים כדי לשמור עקביות לאורך פרק ארוך: שאותו
    # שם ייכתב אותו דבר בדקה 3 ובדקה 50. הוא עושה לשם כך חיפוש באינטרנט,
    # וזה החלק האיטי — נמדד 69 שניות על סרטון של 30 שניות. בתמליל קצר
    # אין מה לשמור עליו עקבי, והמחיר הוא כל זמן ההמתנה של המשתמש.
    # מיפוי הדוברים נשאר תמיד: מגדר חשוב גם בחמש שורות
    if len(numbered) < config.RESEARCH_FACTS_MIN:
        log.info("תמליל קצר (%d תווים) — מדלגים על חילוץ המונחים", len(numbered))
        chunks = []
    else:
        chunks = [numbered[i:i + FACTS_CHUNK]
                  for i in range(0, min(len(numbered),
                                        FACTS_CHUNK * FACTS_CHUNKS_MAX),
                                 FACTS_CHUNK)] or [numbered]

    done = 0
    total = len(chunks) + 1
    gate = asyncio.Lock()
    # מה רץ ברגע זה ומתי התחיל. בלי זה ההתקדמות דיווחה רק בסיום כל
    # קריאה, והמסך נראה תקוע על אותו אחוז כל עוד שלוש הקריאות באוויר —
    # בדיוק התחושה של "נתקע בהתחלה"
    live: dict[str, float] = {}

    async def refresh() -> None:
        if not on_step:
            return
        now = time.monotonic()
        running = " · ".join(f"{name} {int(now - t)}ש"
                             for name, t in sorted(live.items()))
        label = running or "מסכם"
        await on_step(f"חוקר את התוכן {done}/{total} · {label}",
                      RESEARCH_TO * done / total)

    async def ticker() -> None:
        """מזיז את המסך בזמן שהקריאות הארוכות רצות."""
        while True:
            await asyncio.sleep(3)
            async with gate:
                await refresh()

    async def call(name: str, coro) -> str:
        nonlocal done
        started = time.monotonic()
        async with gate:
            live[name] = started
            await refresh()
        try:
            return await coro
        finally:
            spent = time.monotonic() - started
            # המספר שחסר לנו: כמה כל קריאת חקר באמת לוקחת
            log.info("חקר — %s הסתיים ב-%.0f שניות", name, spent)
            async with gate:
                live.pop(name, None)
                done += 1
                await refresh()

    async def people() -> str:
        return await gemini.research(
            PEOPLE_SYSTEM,
            PEOPLE_USER.format(language=language, transcript=_cap(numbered, 120_000)),
            grounded=False,
        )

    async def facts(index: int, chunk: str) -> str:
        # בלי רשת: זו קריאה וחילוץ בלבד, והחיפוש הוא מה שהאט אותה
        return await gemini.research(
            FACTS_SYSTEM,
            FACTS_USER.format(
                titled=(FACTS_TITLE.format(title=title) if title else ""),
                part=index + 1, total=len(chunks),
                language=language, transcript=chunk),
            # עם רשת כשיש שם סרט: רק אז יש מה לחפש שאינו מגיע
            # מהתמליל עצמו. בלי שם, חיפוש כאן רק מאט
            grounded=bool(title),
        )

    async def verify(items: str) -> str:
        """אימות אינטרנט אחד וקצר, רק על מה שסומן כלא ודאי."""
        return await gemini.research(VERIFY_SYSTEM,
                                     VERIFY_USER.format(items=items))

    if on_step:
        await on_step(f"חוקר את התוכן 0/{total}", 0.0)

    deadline = time.monotonic() + config.RESEARCH_BUDGET
    pulse = asyncio.create_task(ticker())
    jobs = [asyncio.ensure_future(call("דוברים", people()))]
    jobs += [asyncio.ensure_future(call(f"עובדות {i + 1}", facts(i, chunk)))
             for i, chunk in enumerate(chunks)]
    try:
        # תקרת זמן לכל השלב. החקר הוא שיפור ולא תנאי, וחיפוש אחד איטי
        # החזיק עד כה את המשתמש בלי שקיבל דבר. מה שהספיק נכנס, מה שלא
        # נזנח — ותרגום עם מסמך חלקי טוב מתרגום שמתחיל שלוש דקות מאוחר
        await asyncio.wait(jobs, timeout=max(1.0, deadline - time.monotonic()))
    finally:
        pulse.cancel()

    late = [job for job in jobs if not job.done()]
    for job in late:
        job.cancel()
    if late:
        log.warning("חרגו מתקרת החקר (%.0fש) ונזנחו %d קריאות מתוך %d",
                    config.RESEARCH_BUDGET, len(late), len(jobs))

    parts = []
    for job in jobs:
        try:
            parts.append(job.result() if job.done() and not job.cancelled()
                         else "")
        except Exception as exc:        # noqa: BLE001 — קריאה שנפלה מדולגת
            log.debug("קריאת חקר נכשלה: %s", exc)
            parts.append("")

    who, *found = parts
    sections = [who.strip()] if who.strip() else []
    merged = "\n\n".join(part.strip() for part in found if part.strip())
    if merged:
        sections.append("שמות, מונחים וציטוטים שאותרו:\n" + merged)

    # אימות ברשת רק אם יש מה לאמת. שורות שסומנו ב-(?) הן בדיוק אלה
    # שהמודל אינו בטוח בהן; כשאין אף אחת, אין סיבה לצאת לרשת בכלל
    unsure = [line for line in merged.splitlines() if "(?)" in line]
    if unsure:
        trimmed = "\n".join(unsure[:config.VERIFY_MAX_ITEMS])
        log.info("אימות ברשת: %d פריטים לא ודאיים (מתוך %d שורות)",
                 len(unsure), len(merged.splitlines()))
        # האימות היה מחוץ לתקרה, ולכן שלב שתוקצב ל-150 שניות נמדד
        # ב-510: שש דקות של חיפוש ברשת בלי שום גבול. הוא חולק את אותה
        # תקרה עם השאר ומקבל את מה שנשאר ממנה
        spare = deadline - time.monotonic()
        if spare < config.VERIFY_MIN_SECONDS:
            log.info("לא נותר זמן בתקרת החקר (%.0fש) — מדלגים על האימות",
                     spare)
            checked = ""
        else:
            try:
                checked = await asyncio.wait_for(
                    call("אימות ברשת", verify(trimmed)), timeout=spare)
            except (Exception, asyncio.TimeoutError) as exc:   # noqa: BLE001
                log.warning("האימות נכשל או חרג ומדולג: %s", exc)
                checked = ""
        if checked.strip():
            sections.append("איותים שאומתו:\n" + checked.strip())
    else:
        log.info("אין פריטים לא ודאיים — מדלגים על חיפוש ברשת")
    notes = "\n\n".join(sections)
    log.info("מסמך הנחיות נוצר: %d תווים מתוך %d קריאות", len(notes), total)
    return notes


async def build_hebrew(segments: list[Segment], language: str,
                       on_step=None, title: str = "") -> tuple[list[str], str]:
    """מחזיר את שורות העברית (באורך ובסדר של הסגמנטים) ואת מסמך ההנחיות."""
    numbered = "\n".join(f"[{s.index}] {s.text}" for s in segments)

    async def staged(label: str, coro):
        """מריץ שלב ומדווח כמה מהזמן שלו עבר בהמתנה למכסה.

        השאלה "המפתחות מגבילים אותנו או שהקריאות פשוט איטיות" חזרה שוב
        ושוב ואי אפשר היה להכריע בה מהצד. כאן היא נענית במספרים: המתנה
        למפתח פנוי מול המתנה לתשובת המודל, ומספר ה-429 בפועל
        """
        gemini.tally.reset()
        started = time.monotonic()
        result = await coro
        log.info("%s · סה״כ %.0fש | %s", label,
                 time.monotonic() - started, gemini.tally.report(label))
        return result

    notes = await staged("חקר",
                         research_notes(numbered, language, on_step, title))
    if not notes:
        notes = "לא התקבל מסמך הנחיות. הסק מגדרים ונמענים מתוך הקונטקסט עצמו, בזהירות."

    # המגדר נקבע פעם אחת, מזיהוי הדוברים, ונעוץ בכל חלון תרגום. קריאה
    # אחת קטנה שמייתרת סריקה שלמה אחריה
    if on_step:
        await on_step("מזהה את מגדר הדוברים", RESEARCH_TO)
    genders, sure = await staged("מגדר דוברים",
                                 speaker_genders(segments, language, notes))

    lines = await staged("תרגום",
                         _translate_all(segments, language, notes, on_step,
                                        genders))
    if sure and not config.ADDRESSEE_ALWAYS:
        log.info("מדלגים על מעבר מגדר הפנייה — הטבלה הכריעה את כל הדוברים")
    else:
        if on_step:
            await on_step("מתאים מגדר פנייה", TRANSLATE_TO)
        lines = await staged("מגדר פנייה",
                             enforce_addressee(segments, lines, notes, on_step))
    if on_step:
        await on_step("בודק איכות ועקביות", ADDRESSEE_TO)
    lines = await staged("בקרת איכות",
                         _quality_pass(segments, lines, notes, on_step))

    # ניקוי ארטיפקטים: ניקוד מוסר ישירות, אותיות זרות נשלחות לתיקון ממוקד
    lines, foreign = cleanup.clean(lines)
    if on_step:
        await on_step("מסיים", QUALITY_TO)
    if foreign:
        if on_step:
            await on_step("מתקן אותיות זרות", QUALITY_TO)
        lines = await repair_foreign(segments, lines, foreign, on_step)
        lines, _ = cleanup.clean(lines)

    return lines, notes


async def _translate_all(segments: list[Segment], language: str, notes: str,
                         on_step=None, genders: str = "") -> list[str]:
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
    # אותו תיקון שנעשה בשלב החקר: בלי דיווח בזמן אמת, חלון שרץ דקה
    # משאיר על המסך את ההודעה של השלב הקודם — ונראה כאילו שום דבר לא
    # קורה. בקליפ קצר יש חלון אחד בלבד, ואז זה כל משך התרגום
    live: dict[int, float] = {}
    report_lock = asyncio.Lock()
    log.info("מתרגם %d חלונות, עד %d במקביל", len(starts), workers)

    async def refresh() -> None:
        if not on_step:
            return
        now = time.monotonic()
        if live:
            oldest = int(now - min(live.values()))
            # למה זה לוקח זמן, ולא רק כמה. חלון בודד שרץ דקה נראה
            # זהה בשני המקרים, והמשתמש אינו יכול לדעת אם אנחנו חנוקים
            # במכסת המפתחות או שהמודל עצמו איטי
            stuck = gemini.waiting_for_key()
            why = " · ממתין למפתח" if stuck else " · ממתין למודל"
            note = (f"מתרגם {finished}/{len(segments)} שורות · "
                    f"{len(live)} חלונות בעבודה · {oldest}ש{why}")
        else:
            note = f"מתרגם {finished}/{len(segments)} שורות"
        await on_step(note, TRANSLATE_FROM + (TRANSLATE_TO - TRANSLATE_FROM)
                      * finished / max(1, len(segments)))

    async def ticker() -> None:
        while True:
            await asyncio.sleep(3)
            async with report_lock:
                await refresh()

    async def translate_window(start: int) -> None:
        nonlocal finished
        async with report_lock:
            live[start] = time.monotonic()
            await refresh()
        window = segments[start:start + WINDOW]
        before = segments[max(0, start - CONTEXT):start]
        after = segments[start + WINDOW:start + WINDOW + CONTEXT]

        pinned = pinned_genders(notes)

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
            try:
                # התקרה חסרה כאן והייתה רק בהתאמת המגדר ובבקרת האיכות.
                # נמדד אצל המשתמש: "מתרגם 609/659 · 1 חלונות בעבודה ·
                # ממתין למודל · אין תזוזה 6:25". חלון אחד תקוע מחזיק
                # את כל התרגום, ושבע מכסות ג'מיני אינן עוזרות לו —
                # בקשה בודדת רצה על מפתח אחד
                result = await asyncio.wait_for(
                    gemini.ask_json(TRANSLATE_SYSTEM, prompt, schema=schema),
                    timeout=config.GEMINI_WINDOW_TIMEOUT)
            except asyncio.TimeoutError:
                log.warning("חלון תרגום עבר %.0f שניות — השורות שלו "
                            "יטופלו אחת-אחת",
                            config.GEMINI_WINDOW_TIMEOUT)
                result = {}
        got = _collect(result)
        for seg in window:
            out[seg.index] = (got.get(seg.index) or "").strip()

        missing = [s.index for s in window if not out[s.index]]
        # חלון שנפל כולו אינו מטופל שורה-שורה. המסלול הזה נבנה
        # לכמה שורות שהמודל השמיט, והוא רץ בטור: חלון של חמישים
        # שורות שנחתך בתקרה הפך לחמישים קריאות רצופות, כל אחת עד
        # GEMINI_WINDOW_TIMEOUT, בעוד הן מחזיקות מקום בגייט.
        # נמדד אצל המשתמש: "2 חלונות בעבודה · אין תזוזה 13:35".
        #
        # במקום זה ניסיון שני אחד על החלון כולו, ואם גם הוא נפל —
        # טקסט המקור. שורה באנגלית גרועה פחות משעה של המתנה
        if missing and len(missing) == len(window):
            log.warning("חלון %d-%d חזר ריק — ניסיון שני על החלון כולו",
                        window[0].index, window[-1].index)
            async with gate:
                again = await _bounded(gemini.ask_json(
                    TRANSLATE_SYSTEM, prompt, schema=schema))
            got = _collect(again)
            for seg in window:
                out[seg.index] = (got.get(seg.index) or "").strip()
            missing = [s.index for s in window if not out[s.index]]
            if missing:
                log.warning("חלון %d-%d נכשל פעמיים — %d שורות נשארות "
                            "בשפת המקור", window[0].index, window[-1].index,
                            len(missing))
                for idx in missing:
                    out[idx] = segments[idx].text
                missing = []
        elif len(missing) > config.TRANSLATE_RETRY_MAX:
            # גם כשרק חלק חסר, יש גבול. מעבר לו עדיף המקור
            log.warning("%d שורות חסרות בחלון — מתקנים %d ומשאירים "
                        "את השאר במקור", len(missing),
                        config.TRANSLATE_RETRY_MAX)
            for idx in missing[config.TRANSLATE_RETRY_MAX:]:
                out[idx] = segments[idx].text
            missing = missing[:config.TRANSLATE_RETRY_MAX]
        # שורה שאיבדה מספר מטופלת כמו שורה חסרה: אותו מסלול, עם הוראה
        # מפורשת. בלי זה "Not so fast, 511" ממשיך להגיע למשתמש כ"לא כל
        # כך מהר, מטר עשרים" — שגיאת תוכן שהצופה מבחין בה
        damaged = {s.index: lost_numbers(s.text, out[s.index])
                   for s in window if out[s.index]}
        damaged = {i: nums for i, nums in damaged.items() if nums}
        for idx in list(missing) + list(damaged):
            seg = segments[idx]
            nums = damaged.get(idx)
            demand = ""
            if nums:
                demand = ("חובה שהמספרים הבאים יופיעו בתרגום כספרות, "
                          f"בדיוק כפי שהם: {', '.join(nums)}. "
                          "אלה קודים או מספרי זיהוי, לא מידות — אין "
                          "לפרש אותם ואין להמיר אותם למילים.\n")
            async with gate:
                # גם הניסיון החוזר חסום בזמן: בלעדיו חלון שנחתך
                # בתקרה היה חוזר כאן כשורות בודדות בלי שום גבול
                retry = await _bounded(gemini.ask_json(
                    TRANSLATE_SYSTEM,
                    f"מסמך הנחיות:\n{_cap(notes, 8000)}\n\n"
                    f"{demand}"
                    f"תרגם לעברית שורת כתובית אחת (שפת מקור {language}). "
                    f'הקשר: "{_window_text(segments, idx)}"\n'
                    f'השורה לתרגום: "{seg.text}"\n'
                    'החזר JSON: {"lines":[{"i":%d,"he":"..."}]}' % idx,
                    schema=schema, temperature=0.3,
                ))
            fixed = (_collect(retry).get(idx) or "").strip()
            if nums:
                # שומרים את הניסיון החוזר רק אם הוא באמת החזיר את
                # המספרים. אחרת עדיף התרגום הראשון מאשר הימור שני
                if fixed and not lost_numbers(seg.text, fixed):
                    log.info("שורה %d: המספר %s הוחזר לתרגום",
                             idx, ", ".join(nums))
                    out[idx] = fixed
                else:
                    log.warning("שורה %d: המספר %s אבד בתרגום ולא שוחזר",
                                idx, ", ".join(nums))
            else:
                out[idx] = fixed or seg.text

        finished += len(window)
        log.info("תורגמו %d/%d שורות", finished, len(segments))
        async with report_lock:
            live.pop(start, None)
            await refresh()

    pulse = asyncio.create_task(ticker())
    try:
        # חלון אחד שנכשל אינו מפיל את הסרט. קודם כל חריגה עלתה דרך
        # gather והרגה את כל התרגום — נמדד בשרת: "לא התקבל JSON תקין
        # מ-Gemini" על חלון בודד, בזמן שכבר תורגמו 1056 מתוך 1606
        # שורות. כל העבודה הזאת נזרקה בגלל חלון אחד.
        #
        # עכשיו החריגות נאספות, מה שהצליח נשמר, ומה שנשאר ריק יקבל
        # את המקור בתור גיבוי מספר שורות למטה — עדיף סרט עם חלון
        # אחד בשפת המקור מאשר שום סרט
        done = await asyncio.gather(
            *(translate_window(start) for start in starts),
            return_exceptions=True)
    finally:
        pulse.cancel()

    broken = [item for item in done if isinstance(item, BaseException)]
    if broken:
        log.error("%d מתוך %d חלונות תרגום נכשלו (%s) — ממשיכים עם מה שיש",
                  len(broken), len(starts),
                  "; ".join(f"{type(e).__name__}: {e}" for e in broken[:3]))
        if len(broken) == len(starts):
            # אף חלון לא עבר. כאן באמת אין סרט, וכישלון שקט יהיה גרוע
            # יותר מהודעה ברורה
            raise broken[0]

    empty = [index for index, text in enumerate(out) if not (text or "").strip()]
    if empty:
        log.warning("%d שורות נשארו בלי תרגום — נשמר המקור שלהן",
                    len(empty))
        for index in empty:
            out[index] = segments[index].text
    return out


# שורות בכל קריאת בקרת איכות. קודם זו הייתה קריאה אחת על כל הכתוביות
# (עד 200,000 תווים): מפתח אחד עבד בזמן שכל השאר עמדו פנויים, והשלב כולו
# היה חסום על הקריאה האיטית הזאת. חלונות מקביליים מנצלים את כל המפתחות,
# ובונוס: חלון קצר מקבל תשומת לב טובה יותר מהמודל מאשר ערימה ענקית
def _digits(text: str) -> list[str]:
    """רצפי ספרות באורך שלוש ומעלה, בלי מפרידי אלפים.

    שלוש ומעלה בכוונה: מספרים קטנים נכתבים בעברית במילים ("תשעה מייל"
    עבור nine miles) וזו כתיבה תקינה. אבל 511, 1969 ו-2,000 הם קודים,
    שנים וכמויות — הם חייבים לשרוד את התרגום כספרות.
    """
    # הנקודה של סוף המשפט נבלעה ברצף ויצרה "511." — ואז המספר נחשב
    # אבוד גם כשהתרגום הכיל אותו. מסירים פיסוק נגרר
    found = re.findall(r"\d[\d.]*", text.replace(",", ""))
    return [d for d in (f.rstrip(".") for f in found) if len(d) >= 3]


def lost_numbers(source: str, hebrew: str) -> list[str]:
    """מספרים שהיו במקור ונעלמו בתרגום.

    תפס את "Not so fast, 511" שהפך ל"לא כל כך מהר, מטר עשרים": המודל
    פירש מספר טיסה כמידת גובה. זו מחלקה שלמה של שגיאות — קודים, מספרי
    טיסה, שנים ודגמים שמתורגמים במקום להיות מועתקים — והיא היחידה
    מבין פגמי התרגום שניתן לזהות בוודאות בלי לקרוא את התוכן
    """
    if not source or not hebrew:
        return []
    flat = hebrew.replace(",", "")
    return [d for d in _digits(source) if d not in flat]


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
    pinned = pinned_genders(notes)
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


async def _bounded(coro, default: dict | None = None) -> dict:
    """מריץ קריאה עם תקרת זמן, ומחזיר ריק כשהיא עברה.

    שורה בודדת שנתקעת אינה שווה את העבודה כולה: בלי התקרה היא
    מחזיקה את הגייט, ואחריה את כל שאר השורות שממתינות לו
    """
    try:
        return await asyncio.wait_for(coro,
                                      timeout=config.GEMINI_WINDOW_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("קריאה בודדת עברה %.0f שניות ונזנחה",
                    config.GEMINI_WINDOW_TIMEOUT)
        return default if default is not None else {}
    except gemini.GeminiError as exc:
        log.warning("קריאה בודדת נכשלה: %s", exc)
        return default if default is not None else {}


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
        async def step() -> None:
            nonlocal done
            async with lock:
                done += 1
                if on_step:
                    await on_step(f"בודק איכות {done}/{len(starts)}",
                                  ADDRESSEE_TO + (1.0 - ADDRESSEE_TO)
                                  * done / max(1, len(starts)))

        try:
            # אותה תקרה כמו בהתאמת המגדר, ומאותה סיבה
            result = await asyncio.wait_for(
                gemini.ask_json(CHECK_SYSTEM, prompt,
                                schema=_QUALITY_SCHEMA, temperature=0.0),
                timeout=config.GEMINI_WINDOW_TIMEOUT)
        except (gemini.GeminiError, asyncio.TimeoutError) as exc:
            # חלון שנכשל לא מפיל את השאר. קודם כשל יחיד החזיר את כל
            # התרגום בלי שום בדיקת איכות.
            # והוא גם נספר: בלי זה המונה נתקע על 14/15 לנצח
            log.warning("חלון בקרת איכות נכשל ומדולג: %s",
                        exc or type(exc).__name__)
            await step()
            return []
        await step()
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
_CAST_LINE = re.compile(r"^@דמויות:\s*(.+)$", re.MULTILINE)


SPEAKER_SYSTEM = (
    "אתה מנתח דוברים בתסריט. מזהה לכל דובר את מגדרו הדקדוקי בעברית, "
    "ואת מגדר מי שהוא פונה אליו. חשוב: בעברית צורת זכר משמשת גם כצורה "
    "גנרית, ולכן אל תסיק מגדר נמען מצורת הפנייה בטקסט — הסק אותו ממי "
    "שבפועל נמצא בשיחה. כשאין די ראיות החזר \"לא ידוע\" ולא ניחוש."
)

# כמה שורות לדגום מכל דובר. די בהן כדי להכריע מגדר, והן קטנות מספיק
# כדי שכל הדוברים ייכנסו לקריאה אחת
SPEAKER_SAMPLE = 12


async def speaker_genders(segments: list[Segment], language: str,
                          notes: str = "") -> tuple[str, bool]:
    """טבלת דובר→מגדר מתוך זיהוי הדוברים. מחזיר (שורה לנעיצה, ודאי?).

    עד כה המגדר נשרף ממסמך החקר בביטוי רגולרי שחיפש "@מגדר:". כשהמסמך
    ניסח אחרת — וזה קורה — לא ננעץ דבר, והתרגום חזר לנחש מגדר מתוך
    הטקסט. זו בדיוק הנקודה שבה הזכר והנקבה מתהפכים באמצע שיחה.

    כאן המגדר נקבע מהנתון שכבר יש לנו ולא מניסוח: התמלול מחזיר מי אמר
    כל מילה, ולכן אפשר לשאול פעם אחת, בשאלה ממוקדת, מה המגדר של כל
    דובר — ולנעוץ את התשובה בכל חלון תרגום כעובדה ולא כהשערה.

    קריאה אחת קטנה לכל הסרטון, והיא חוסכת מעבר תיקון שלם
    """
    speakers: dict[str, list[str]] = {}
    for segment in segments:
        who = getattr(segment, "speaker", "")
        if who and len(speakers.setdefault(who, [])) < SPEAKER_SAMPLE:
            speakers[who].append(segment.text)
    if not speakers:
        # אין זיהוי דוברים — נשארים עם מה שמסמך החקר הצליח לומר
        return gender_table(notes), False

    sample = "\n\n".join(
        f"דובר {who}:\n" + "\n".join(f"- {line}" for line in lines)
        for who, lines in speakers.items())
    schema = {
        "type": "object",
        "properties": {"speakers": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "gender": {"type": "string",
                           "enum": ["זכר", "נקבה", "לא ידוע"]},
                "addressee": {"type": "string",
                              "enum": ["זכר", "נקבה", "רבים", "לא ידוע"]},
            },
            "required": ["id", "gender", "addressee"]}}},
        "required": ["speakers"],
    }
    try:
        answer = await gemini.ask_json(
            SPEAKER_SYSTEM,
            f"שפת המקור: {language}\n\n{_cap(sample, 12_000)}\n\n"
            "לכל דובר: מה מגדרו, ולאיזה מגדר הוא פונה ברוב דבריו?",
            schema=schema)
    except Exception as exc:  # noqa: BLE001 — נופלים למסמך החקר
        log.warning("זיהוי מגדר הדוברים נכשל (%s) — נשארים על מסמך החקר", exc)
        return gender_table(notes), False

    rows, sure = [], True
    for item in (answer or {}).get("speakers", []) if isinstance(answer, dict) else []:
        who = str(item.get("id", "")).strip()
        mine = str(item.get("gender", "")).strip()
        theirs = str(item.get("addressee", "")).strip()
        if not who or not mine:
            continue
        if mine == "לא ידוע" or theirs == "לא ידוע":
            sure = False
        rows.append(f"דובר {who}: מדבר כ{mine}, פונה ל{theirs}")
    if not rows:
        return gender_table(notes), False
    log.info("מגדר הדוברים נקבע מזיהוי הדוברים: %d דוברים, %s",
             len(rows), "ודאי" if sure else "חלקי")
    return " · ".join(rows)[:600], sure


def gender_table(notes: str) -> str:
    """מחלץ את שורת המגדר ממסמך החקר.

    סעיף 6: המסמך כבר נשאל על מגדר הדוברים, אבל ענה בפרוזה בתוך 20,000
    תווים. בכל חלון תרגום המודל נדרש לחלץ אותה מחדש מתוך ההקשר הארוך,
    וזה בדיוק המקום שבו המגדר מתהפך באמצע שיחה. שורה אחת קצרה שנעוצה
    בראש כל חלון עולה אפס קריאות ואינה משאירה מקום לפרשנות.
    """
    found = _GENDER_LINE.search(notes or "")
    if not found:
        log.warning("אין שורת @מגדר במסמך החקר — התרגום ירוץ בלי "
                    "טבלת מגדר דוברים")
        return ""
    row = " ".join(found.group(1).split())[:300]
    if row.strip() in ("אין", "-", "—"):
        return ""
    return row


def pinned_genders(notes: str) -> str:
    """שתי שורות המגדר שנעוצות בראש כל קטע תרגום.

    טבלת הדמויות קודמת בכוונה: היא לפי שם, ולכן עובדת גם בלי זיהוי
    דוברים, והיא זו שעונה על "אל מי פונים"
    """
    rows = []
    cast = cast_table(notes)
    if cast:
        rows.append("מגדר הדמויות (מחייב, לפי שם): " + cast)
    speakers = gender_table(notes)
    if speakers:
        rows.append("מגדר הדוברים (מחייב): " + speakers)
    if not rows:
        return ""
    rows.append("אל תסיק מגדר מצורת הפנייה בתמליל המקור — באנגלית "
                "אין הבחנה, ובעברית זו בדיוק השגיאה.")
    return "\n".join(rows) + "\n\n"


def cast_table(notes: str) -> str:
    """מגדר לכל דמות, לפי שמה.

    זו הטבלה העמידה מבין השתיים. טבלת הדוברים ממופתחת לאותיות
    שמגיעות מזיהוי דוברים, וכשהוא חסר היא חסרת ערך לגמרי. שם של
    דמות מופיע בדיאלוג עצמו, ולכן הטבלה הזאת עובדת תמיד.

    והיא גם עונה על השאלה הנכונה. טבלת הדוברים אומרת מי **מדבר**,
    ו-12 השגיאות שנמדדו מול תרגום אולפן היו כולן על מי שפונים
    **אליו**: "את משוגעת?", "את הבעלים החדשה?" — לדעת מי מדבר אינו
    מספיק כדי לדעת למי
    """
    found = _CAST_LINE.search(notes or "")
    if not found:
        log.warning("אין שורת @דמויות במסמך החקר — המגדר יישען על "
                    "הקשר בלבד, וזו הנקודה שבה הוא נשבר")
        return ""
    return " ".join(found.group(1).split())[:400]


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…[נחתך]"
