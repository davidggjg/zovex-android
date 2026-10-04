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

import logging

from . import gemini
from .stt import Segment

log = logging.getLogger(__name__)

WINDOW = 35          # שורות שמתורגמות בקריאה אחת
CONTEXT = 12         # שורות הקשר לפני ואחרי (לא מתורגמות שוב)

RESEARCH_SYSTEM = """אתה עורך לשוני ראשי באולפן כתוביות מקצועי בישראל.
לפניך תמליל גולמי של סרטון. התפקיד שלך הוא לחקור אותו לעומק לפני התרגום,
ולהשתמש בחיפוש באינטרנט לכל דבר שאתה לא מזהה בוודאות: שמות של אנשים,
מקומות, מוצרים, מושגים מקצועיים, ציטוטים, מקורות, ראשי תיבות וסלנג.
אתה כותב מסמך הנחיות שעל פיו יתרגמו אחרים. דיוק עובדתי קודם לכל."""

RESEARCH_USER = """להלן תמליל גולמי (שפת מקור: {language}).
חקור וכתוב מסמך הנחיות בעברית, בסעיפים הבאים בדיוק:

1. נושא והקשר: על מה הסרטון, סוג התוכן (שיעור / פודקאסט / חדשות / סרטון שיווקי / שיחה פרטית / הרצאה), ורמת המשלב הנדרשת בעברית.
2. דוברים: רשימת הדוברים שזוהו, ולכל אחד — מגדר (זכר/נקבה/לא ידוע) ועל מה הסתמכת (שם, פנייה אליו, צורות דקדוק במקור, הקשר).
3. נמענים: אל מי כל דובר פונה בכל חלק — יחיד זכר, יחידה נקבה, רבים מעורב, קהל. זה הסעיף הקריטי ביותר: ציין במפורש היכן הפנייה מתחלפת (למשל "מדקה 4 ואילך הוא פונה לאישה — צריך לשון נקבה").
4. שמות פרטיים: כל שם של אדם/מקום/חברה/מוצר, והאיות הנכון בעברית. חפש באינטרנט כדי לאמת איות של שמות לא מוכרים.
5. מונחים: טבלת מונחים מקצועיים — מונח במקור ⇒ התרגום הקבוע שישמש בכל הסרטון.
6. ציטוטים ומקורות: אם מצוטט פסוק, שיר, חוק, מחקר או נתון — אמת אותו בחיפוש וכתוב את הנוסח המדויק.
7. שגיאות תמלול: מילים שנשמע שהתמלול שיבש, ומה הכוונה המקורית הסבירה.
8. אזהרות: כל דבר נוסף שמתרגם חייב לדעת.

התמליל:
{transcript}"""

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

מחזיר תמיד JSON בלבד."""

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
משמעות. מחזיר תמיד JSON בלבד."""


async def enforce_addressee(segments: list[Segment], lines: list[str],
                            notes: str) -> list[str]:
    """מעבר ייעודי אחד: קובע נמען לכל שורה ואוכף עליה את הצורה הנכונה."""
    paired = "\n".join(
        f"[{i}] מקור: {segments[i].text}\n[{i}] עברית: {lines[i]}"
        for i in range(len(segments)) if lines[i]
    )
    schema = {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "i": {"type": "integer"},
                        "addressee": {"type": "string"},
                        "he": {"type": "string"},
                        "changed": {"type": "boolean"},
                    },
                    "required": ["i", "addressee", "he", "changed"],
                },
            }
        },
        "required": ["lines"],
    }
    prompt = f"""מסמך הנחיות:
---
{_cap(notes, 15_000)}
---

הכתוביות:
{_cap(paired, 150_000)}

עבור על כל השורות לפי הסדר. לכל שורה החזר:
  i — האינדקס
  addressee — אחד מ: "יחיד", "יחידה", "רבים", "אין"
  he — השורה בעברית, מתוקנת אם הצורה לא תאמה את הנמען, אחרת כמו שהיא
  changed — true רק אם שינית

זכור את כלל הרצף: שורות עוקבות של אותו דובר אל אותו נמען חייבות אותה צורה.
החזר JSON: {{"lines": [...]}}"""

    try:
        result = await gemini.ask_json(ADDRESSEE_SYSTEM, prompt, schema=schema,
                                       temperature=0.0)
    except gemini.GeminiError as exc:
        log.warning("מעבר הנמענים נכשל: %s", exc)
        return lines

    items = result.get("lines") if isinstance(result, dict) else result
    changed = 0
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
    log.info("מעבר הנמענים תיקן %d שורות", changed)
    return lines


async def build_hebrew(segments: list[Segment], language: str,
                       on_step=None) -> tuple[list[str], str]:
    """מחזיר את שורות העברית (באורך ובסדר של הסגמנטים) ואת מסמך ההנחיות."""
    numbered = "\n".join(f"[{s.index}] {s.text}" for s in segments)

    notes = await gemini.research(
        RESEARCH_SYSTEM,
        RESEARCH_USER.format(language=language, transcript=_cap(numbered, 120_000)),
    )
    if notes:
        log.info("מסמך הנחיות נוצר (%d תווים)", len(notes))
    else:
        notes = "לא התקבל מסמך הנחיות. הסק מגדרים ונמענים מתוך הקונטקסט עצמו, בזהירות."

    lines = await _translate_all(segments, language, notes, on_step)
    if on_step:
        await on_step("מתאים מגדר פנייה", 0.93)
    lines = await enforce_addressee(segments, lines, notes)
    if on_step:
        await on_step("בודק עקביות", 0.97)
    lines = await _quality_pass(segments, lines, notes)
    return lines, notes


async def _translate_all(segments: list[Segment], language: str, notes: str,
                         on_step=None) -> list[str]:
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

    for start in range(0, len(segments), WINDOW):
        window = segments[start:start + WINDOW]
        before = segments[max(0, start - CONTEXT):start]
        after = segments[start + WINDOW:start + WINDOW + CONTEXT]

        prompt = f"""מסמך הנחיות לסרטון הזה:
---
{_cap(notes, 20_000)}
---

שפת המקור: {language}

הקשר קודם (לקריאה בלבד, כבר תורגם):
{_numbered(before) or "(תחילת הסרטון)"}

הקשר הבא (לקריאה בלבד, אל תתרגם):
{_numbered(after) or "(סוף הסרטון)"}

תרגם לעברית את השורות הבאות בלבד, לפי האינדקסים שלהן:
{_numbered(window)}

החזר JSON: {{"lines": [{{"i": <אינדקס>, "he": "<עברית>"}}, ...]}}
חובה להחזיר בדיוק {len(window)} פריטים, אינדקס לכל שורה שביקשתי."""

        result = await gemini.ask_json(TRANSLATE_SYSTEM, prompt, schema=schema)
        got = _collect(result)
        for seg in window:
            out[seg.index] = (got.get(seg.index) or "").strip()

        missing = [s.index for s in window if not out[s.index]]
        if missing:
            log.warning("חסרות %d שורות בחלון %d — מנסה שוב אחת-אחת", len(missing), start)
            for idx in missing:
                seg = segments[idx]
                retry = await gemini.ask_json(
                    TRANSLATE_SYSTEM,
                    f"מסמך הנחיות:\n{_cap(notes, 8000)}\n\n"
                    f"תרגם לעברית שורת כתובית אחת (שפת מקור {language}). "
                    f"הקשר: \"{_window_text(segments, idx)}\"\n"
                    f"השורה לתרגום: \"{seg.text}\"\n"
                    'החזר JSON: {"lines":[{"i":%d,"he":"..."}]}' % idx,
                    schema=schema, temperature=0.3,
                )
                out[idx] = (_collect(retry).get(idx) or seg.text).strip()
        done = min(start + WINDOW, len(segments))
        log.info("תורגמו %d/%d שורות", done, len(segments))
        if on_step:
            await on_step(f"מתרגם {done}/{len(segments)} שורות",
                          0.05 + 0.90 * done / max(1, len(segments)))
    return out


async def _quality_pass(segments: list[Segment], lines: list[str], notes: str) -> list[str]:
    """סריקה על כל הכתוביות בבת אחת, ואחריה תיקון ממוקד."""
    paired = "\n".join(
        f"[{i}] מקור: {segments[i].text}\n[{i}] עברית: {lines[i]}"
        for i in range(len(segments)) if lines[i]
    )
    schema = {
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
    prompt = f"""מסמך הנחיות:
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

    try:
        result = await gemini.ask_json(CHECK_SYSTEM, prompt, schema=schema, temperature=0.0)
    except gemini.GeminiError as exc:
        log.warning("בדיקת האיכות נכשלה, מחזיר את התרגום כמו שהוא: %s", exc)
        return lines

    fixes = result.get("fixes") if isinstance(result, dict) else None
    applied = 0
    for fix in fixes or []:
        try:
            idx = int(fix["i"])
            text = str(fix["he"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < len(lines) and text and text != lines[idx]:
            log.info("תיקון [%d]: %s", idx, str(fix.get("why", ""))[:120])
            lines[idx] = text
            applied += 1
    log.info("בדיקת האיכות תיקנה %d שורות", applied)
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
    return "\n".join(f"[{s.index}] {s.text}" for s in segs)


def _window_text(segments: list[Segment], idx: int) -> str:
    lo, hi = max(0, idx - 3), min(len(segments), idx + 4)
    return " ".join(s.text for s in segments[lo:hi])


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…[נחתך]"
