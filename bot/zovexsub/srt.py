"""בניית קובץ SRT: תזמונים נקיים ופיצול שורות קריא בעברית."""
from __future__ import annotations

import bisect
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from . import config
from .stt import Segment

log = logging.getLogger(__name__)

# מילים שעדיף לא להשאיר בסוף שורה — הן פותחות את ההמשך
_OPENERS = {
    "של", "עם", "על", "אל", "את", "כי", "אם", "לא", "גם", "או", "כל", "זה",
    "אבל", "כדי", "לפני", "אחרי", "בתוך", "בגלל", "כמו", "יותר", "פחות",
    "אני", "אתה", "את", "הוא", "היא", "אנחנו", "אתם", "אתן", "הם", "הן",
}


@dataclass
class Cue:
    index: int
    start: float
    end: float
    text: str


# כמה מותר להזיז כתובית כדי להצמיד אותה לדיבור שזוהה.
#
# היה כאן מספר אחד, 25 שניות, בנימוק ש-Whisper עובד בחלונות של 30 שניות
# וחלון מלא מוזיקה מחזיר כתובית שמתחילה בתחילת החלון. הנימוק נכון לתמלול
# גולמי בלבד — אבל כשהתזמונים כבר מדויקים (יישור כפוי, או חותמות מילים
# מג'מיני) הוא הפך למסוכן: היתר להזיז כתובית נכונה עד 25 שניות הוא היתר
# לזרוק אותה למקום אחר בסרט בגלל טעות זיהוי אחת של ה-VAD.
#
# לכן שני ערכים, לפי מידת הדיוק של המקור
# מקדימים את הכתובית במעט כדי לא לחתוך את ההברה הראשונה
LEAD_IN = 0.12


def build_cues(segments: list[Segment], lines: list[str],
               speech: list[tuple[float, float]] | None = None,
               accurate: bool = False) -> list[Cue]:
    # zip עוצר ברשימה הקצרה, בשקט. אם התרגום חזר קצר ולו בשורה אחת,
    # כל הזנב של הסרט נעלם בלי שגיאה ובלי לוג — וזה נראה למשתמש
    # כמו "חור בכתוביות" שאי אפשר לאבחן. כאן זה נאמר, והרשימה
    # מרופדת כדי שהאובדן יהיה שורה אחת ולא כל מה שאחריה
    if len(lines) != len(segments):
        log.error("התרגום החזיר %d שורות מול %d סגמנטים — מרפדים "
                  "כדי לא לאבד את הזנב", len(lines), len(segments))
        lines = list(lines)[:len(segments)]
        lines += [""] * (len(segments) - len(lines))

    cues: list[Cue] = []
    for seg, hebrew in zip(segments, lines):
        text = (hebrew or "").strip()
        if not text:
            continue
        cues.append(Cue(0, seg.start, max(seg.end, seg.start + 0.3), text))

    if speech:
        # קודם מתקנים שעון מוסט, ורק אחר כך מצמידים נקודתית. הסדר
        # ההפוך היה מצמיד כל כתובית לדיבור הלא נכון
        # סחיפה מתקדמת קודמת להיסט קבוע: כשהיא קיימת, היסט אחד לכל
        # הקובץ הוא ממילא הממוצע שלה ומשאיר את שני הקצוות שגויים
        base, rate, pivot = drift_fit(cues, speech)
        if rate:
            cues = apply_drift(cues, base, rate, pivot)
        else:
            drift = global_offset(cues, speech)
            # שתי מדידות, ומעדיפים את זו שאינה נבלעת ברעש. כשהן
            # חלוקות משמעותית, המדידה מתחילות הדיבור היא האמינה:
            # כל ערך בה הוא זוג אמיתי של אמירה וכתובית
            anchored = onset_offset(cues, speech)
            if abs(anchored - drift) >= config.OFFSET_MIN:
                log.warning("המדידות חלוקות: סריקה %.2fש מול תחילות "
                            "דיבור %.2fש — בוחרים בשנייה", drift, anchored)
                drift = anchored
            if abs(drift) >= config.OFFSET_MIN:
                log.warning("הכתוביות %s ב-%.2f שניות באופן שיטתי — מתוקן",
                            "מאחרות" if drift > 0 else "מקדימות", abs(drift))
                cues = apply_offset(cues, drift)
            else:
                log.info("אין היסט שיטתי בתזמונים (%.2fש)", drift)
        cues = _snap_to_speech(cues, speech, accurate)
    cues = trim_tail(cues)
    # נקודה בודדת או מקף אינם כתובית, והם צצו על המסך
    blank = drop_blank(cues)
    if blank:
        log.info("הוסרו %d כתוביות ריקות מתוכן", blank)
    cues = merge_short(cues)
    cues = _fix_timing(cues)
    # ההקדמה אחרונה, ובכוונה. היא מקטינה כל מרווח בין כתוביות, וקודם
    # לכן היא שינתה גם את החלטות המיזוג — תופעת לוואי שלא ביקשנו.
    # כאן היא נוגעת רק בתזמון הסופי.
    # LEAD_IN שבהצמדה חל על מיעוט הכתוביות בלבד, ולכן רוב הכתוביות
    # נשארו עם האיחור הקבוע של זיהוי הדיבור — וזה הדיליי שנראה בעין
    if config.SRT_LEAD > 0:
        cues = apply_lead(cues, config.SRT_LEAD)

    if speech:
        gaps = missed_speech(cues, speech)
        if gaps:
            lost = sum(end - begin for begin, end in gaps)
            where = " · ".join(f"{int(b) // 60}:{int(b) % 60:02d}"
                               for b, _ in gaps[:6])
            log.warning("%d קטעי דיבור ללא כתובית, %.0f שניות בסך הכל. "
                        "ראשונים: %s", len(gaps), lost, where)
        else:
            log.info("כל קטעי הדיבור שזוהו מכוסים בכתוביות")

    for i, cue in enumerate(cues, 1):
        cue.index = i
        cue.text = wrap(cue.text)
    return cues


def global_offset(cues: list[Cue], speech: list[tuple[float, float]]) -> float:
    """כמה שניות הכתוביות מאחרות או מקדימות באופן שיטתי.

    כתובית בודדת שזזה היא רעש; כולן שזזות יחד הן שעון שיצא מסנכרון —
    בדיוק מה שמשתמש חווה כ"הדובר אומר, ושלוש שניות אחר כך מופיעה
    הכתובית". הצמדה מקומית לא תתקן את זה, כי כולן מוסטות באותו שיעור.

    הגרסה הראשונה חיפשה לכל כתובית את תחילת הדיבור הקרובה אליה ולקחה
    את החציון. זה נשבר: כשההיסט גדול מחצי המרווח בין אמירות, "הקרובה
    ביותר" היא כבר האמירה הבאה, וההיסט יוצא בסימן הפוך. דיליי של שלוש
    שניות זוהה כהקדמה של שתיים, כלומר תיקון שמחמיר פי שניים.

    כאן נסרקים כל ההיסטים האפשריים בטווח, ונבחר זה שמיישר את המספר
    הגדול ביותר של כתוביות אל תחילת דיבור. אין "קרוב ביותר" ואין
    אליאסינג — רק ספירה.
    """
    if not cues or not speech:
        return 0.0
    onsets = sorted(a for a, _ in speech)
    starts = [c.start for c in cues]
    if len(starts) < config.OFFSET_MIN_SAMPLES:
        return 0.0

    def score(shift: float) -> int:
        hits = 0
        for value in starts:
            moved = value - shift
            position = bisect.bisect_left(onsets, moved)
            for near in onsets[max(0, position - 1):position + 1]:
                if abs(near - moved) <= config.OFFSET_TOLERANCE:
                    hits += 1
                    break
        return hits

    step = 0.05
    steps = int(config.OFFSET_SEARCH / step)
    scored = [(index * step, score(index * step))
              for index in range(-steps, steps + 1)]
    best_hits = max(hits for _, hits in scored)

    # כל היסט בתוך טווח הסבילות מיישר את אותן כתוביות ומקבל אותו
    # ניקוד, כך שהמנצחים יוצרים רמה שטוחה. בחירת הראשון שבה נתנה
    # תוצאה נמוכה מהאמת בדיוק ברוחב הסבילות; מרכז הרמה הוא ההיסט
    plateau = [shift for shift, hits in scored if hits == best_hits]
    best = plateau[len(plateau) // 2]

    # התיקון חייב להשתלם בבירור: גם לשפר מול היעדר תיקון, וגם ליישר
    # חלק משמעותי מהכתוביות. אחרת זו התאמה מקרית לרעש
    if best_hits < max(config.OFFSET_MIN_SAMPLES,
                       int(len(starts) * config.OFFSET_MIN_RATIO)):
        return 0.0
    if best_hits <= score(0.0):
        return 0.0
    return best


def missed_speech(cues: list[Cue], speech: list[tuple[float, float]]
                  ) -> list[tuple[float, float]]:
    """קטעי דיבור שזוהו באודיו ולא קיבלו שום כתובית.

    זה הסימפטום של "רעש סופה ברקע ואז אין כתוביות": זיהוי הדיבור שומע
    שמישהו מדבר, אבל התמלול לא הצליח להוציא מילים. בלי המדידה הזאת
    המקרה נראה למשתמש כמו כתובית חסרה אקראית, ואי אפשר לדעת אם מדובר
    בשתיקה אמיתית או בכישלון תמלול.

    המחקר מראה שניקוי רעש דווקא מעלה את שיעור השגיאות של מודלים
    מודרניים, ולכן הצעד הנכון הוא למדוד תחילה כמה באמת אבד.
    """
    if not speech:
        return []
    gaps = []
    for begin, end in speech:
        if end - begin < config.MISSED_MIN:
            continue
        covered = any(c.start < end and c.end > begin for c in cues)
        if not covered:
            gaps.append((begin, end))
    return gaps


def onset_offset(cues: list[Cue], speech: list[tuple[float, float]]
                 ) -> float:
    """ההיסט כפי שהוא נמדד מתחילות הדיבור, ולא מהכתוביות.

    ‏global_offset סורק כל כתובית ושואל אם היא קרובה לתחילת דיבור
    כלשהי. זה נשבר כשיש הרבה יותר כתוביות מתחילות דיבור: ה-VAD
    מוצא כ-200 קטעי דיבור ארוכים, ובתוכם 2000 כתוביות. לרוב
    המוחלט של הכתוביות אין בכלל תחילת־דיבור מתאימה — הן באמצע
    מונולוג — והן נספרות כרעש שמציף את המדד.

    כאן הכיוון הפוך: לכל תחילת דיבור מחפשים את הכתובית הקרובה
    ולוקחים את החציון. כל מדידה היא זוג אמיתי, ואין רעש להציף
    """
    if not cues or not speech:
        return 0.0
    starts = sorted(c.start for c in cues)
    deltas = []
    for begin, _ in speech:
        position = bisect.bisect_left(starts, begin)
        near = [s for s in starts[max(0, position - 1):position + 1]]
        if not near:
            continue
        closest = min(near, key=lambda s: abs(s - begin))
        gap = closest - begin
        # רק התאמות סבירות. כתובית במרחק חמש שניות מתחילת דיבור
        # אינה "הכתובית של אותה אמירה" אלא שכנה מקרית
        if abs(gap) <= config.OFFSET_SEARCH:
            deltas.append(gap)
    if len(deltas) < config.OFFSET_MIN_SAMPLES:
        return 0.0
    deltas.sort()
    middle = deltas[len(deltas) // 2]
    log.info("היסט מתחילות דיבור: חציון %.2fש מתוך %d התאמות",
             middle, len(deltas))
    return middle


def drift_fit(cues: list[Cue], speech: list[tuple[float, float]],
              ) -> tuple[float, float, float]:
    """מודד סחיפה שגדלה עם הזמן. מחזיר (היסט בציר, קצב לשנייה, ציר).

    ‏global_offset מחשב היסט קבוע אחד לכל הקובץ, וזה נכון כשכל
    הכתוביות מוסטות באותו שיעור. אבל כשההיסט **גדל** עם הזמן —
    שעון שרץ מעט מהר מדי — שיפט אחד מיישר את האמצע ומשאיר את שני
    הקצוות שגויים, והפער גדל ככל שהקובץ ארוך יותר.

    זה בדיוק מה שנצפה: פרק של 20 דקות נראה תקין וסרט של שעתיים
    מתפרק. כאן נמדד ההיסט בנפרד בתחילת הקובץ ובסופו, והישר שביניהם
    הוא הסחיפה. התיקון הוא ליניארי ולא קבוע
    """
    if not cues or not speech:
        return 0.0, 0.0, 0.0
    ordered = sorted(cues, key=lambda c: c.start)
    span = ordered[-1].start - ordered[0].start
    if (span < config.DRIFT_MIN_SPAN
            or len(ordered) < config.OFFSET_MIN_SAMPLES * 2):
        return 0.0, 0.0, 0.0

    cut = len(ordered) // 2
    early, late = ordered[:cut], ordered[cut:]
    first = global_offset(early, speech)
    second = global_offset(late, speech)

    def middle(group) -> float:
        return group[len(group) // 2].start

    t_one, t_two = middle(early), middle(late)
    if t_two - t_one < config.DRIFT_MIN_SPAN / 2:
        return 0.0, 0.0, 0.0

    change = second - first
    if abs(change) < config.DRIFT_MIN_CHANGE:
        # הפרש זעיר בין שני החצאים הוא רעש מדידה, לא סחיפה
        return 0.0, 0.0, 0.0
    rate = change / (t_two - t_one)
    if abs(rate) > config.DRIFT_MAX_RATE:
        log.warning("קצב סחיפה חריג (%.4f ש/ש) — מתעלמים", rate)
        return 0.0, 0.0, 0.0
    log.warning("סחיפה מתקדמת: %.2fש בתחילת הקובץ מול %.2fש בסופו "
                "(%.4f ש לכל שנייה) — מתוקן ליניארית", first, second, rate)
    return first, rate, t_one


def apply_drift(cues: list[Cue], base: float, rate: float,
                pivot: float) -> list[Cue]:
    """מזיז כל כתובית לפי ההיסט שלה עצמה, ולא לפי היסט אחד לכולן."""
    for cue in cues:
        shift = base + rate * (cue.start - pivot)
        length = max(0.05, cue.end - cue.start)
        cue.start = max(0.0, cue.start - shift)
        cue.end = cue.start + length
    return cues


def apply_lead(cues: list[Cue], seconds: float) -> list[Cue]:
    """מקדים כל כתובית במעט, בלי לדרוך על זו שלפניה.

    לא אותו דבר כמו תיקון היסט: שם מתקנים שעון שיצא מסנכרון, וכאן
    מפצים על הטיה ידועה וקבועה של זיהוי הדיבור, שמכריז על דיבור רק
    אחרי שהאנרגיה הצטברה. הסוף נשאר במקומו, כדי שהכתובית רק תופיע
    מוקדם יותר ולא תיעלם מוקדם יותר
    """
    # None ולא 0.0: לכתובית הראשונה אין שכנה לפניה, ורצפה של פער
    # הייתה דוחפת אותה קדימה בלי סיבה
    previous_end: float | None = None
    for cue in cues:
        floor = 0.0 if previous_end is None else previous_end + config.SRT_GAP
        cue.start = max(0.0, floor, cue.start - seconds)
        cue.end = max(cue.end, cue.start + config.SRT_MIN_DURATION)
        previous_end = cue.end
    return cues


def apply_offset(cues: list[Cue], seconds: float) -> list[Cue]:
    """מזיז את כל הכתוביות, בלי לחרוג מתחילת הסרטון."""
    for cue in cues:
        cue.start = max(0.0, cue.start - seconds)
        cue.end = max(cue.start + 0.05, cue.end - seconds)
    return cues


def _snap_to_speech(cues: list[Cue], speech: list[tuple[float, float]],
                    accurate: bool = False) -> list[Cue]:
    """מצמיד כל כתובית לדיבור שבאמת נשמע בתוכה.

    כתובית שמתחילה באמצע שקט נדחפת קדימה לרגע שבו הדיבור מתחיל, וסופה
    נמשך אחורה לרגע שבו הדיבור נגמר. בלי זה כתובית שהמודל מתח על פני
    שקט מופיעה שניות לפני שמישהו פותח את הפה.
    """
    limit = config.SNAP_ACCURATE if accurate else config.SNAP_RAW
    moved = 0
    shifts: list[float] = []
    for cue in cues:
        inside = [(a, b) for a, b in speech if b > cue.start + 0.05 and a < cue.end - 0.05]
        if not inside:
            continue
        first = max(0.0, inside[0][0] - LEAD_IN)
        last = inside[-1][1]

        # הכתובית מתחילה בתוך שקט — דוחפים אותה לרגע שהדיבור מתחיל
        if 0.15 < first - cue.start <= limit and first < cue.end - 0.3:
            log.debug("כתובית הוזזה מ-%.2f ל-%.2f", cue.start, first)
            shifts.append(first - cue.start)
            cue.start = first
            moved += 1
        # הכתובית נמשכת לתוך שקט — מושכים את סופה אחורה
        if 0.15 < cue.end - last <= limit and last > cue.start + 0.4:
            cue.end = last + 0.2

    # מדד ולא רק ספירה: הזזה ממוצעת גדולה היא סימן שה-VAD טועה, או
    # שהתזמונים גרועים — ובלי המספר הזה אי אפשר לדעת מי מהם
    if shifts:
        shifts.sort()
        log.info("הוצמדו %d מתוך %d כתוביות · תקרה %.1fש · "
                 "הזזה חציונית %.2fש · מרבית %.2fש",
                 moved, len(cues), limit,
                 shifts[len(shifts) // 2], shifts[-1])
    else:
        log.info("אף כתובית לא נזקקה להצמדה (תקרה %.1fש)", limit)
    return cues


# סימני סוף משפט. כשהחלק הראשון נגמר באחד מהם ושניהם קצרים, סביר
# שמדובר בשני דוברים ולא בהמשך אותו משפט
_ENDS = ".?!״\"'…"


def _two_speakers(first: str, second: str) -> bool:
    """האם שני החלקים נשמעים כמו חילופי דברים ולא כמשפט אחד שנחתך."""
    if not first or not second:
        return False
    return first.rstrip()[-1] in _ENDS and second.lstrip()[0] not in ",.?!…-"


def trim_tail(cues: list["Cue"]) -> list["Cue"]:
    """מסיר הזיות תמלול שנוצרות על הקרדיטים בסוף הסרט.

    מנועי תמלול ממציאים טקסט כשאין דיבור, ועל מוזיקת סיום הם מייצרים
    חתימות של אתרי כתוביות ומילים בודדות. בסרט שנבדק הדיאלוג נגמר
    ב-1:55:57 והקובץ נמשך עד 2:06 עם חמש שורות כאלה.

    הסימן המבחין אינו התוכן אלא הבידוד: בגוף הסרט הפער הגדול ביותר בין
    כתוביות היה 25 שניות, ואילו כל אחת מהשורות האלה ישבה אחרי שתיקה של
    73 עד 187 שניות. לכן הכלל הוא גיאומטרי ולא מילוני — אין רשימת
    ביטויים לתחזק, והוא עובד בכל שפה.
    """
    kept = list(cues)
    removed = []
    while len(kept) >= 2:
        if kept[-1].start - kept[-2].end < config.SRT_TAIL_GAP:
            break
        removed.append(kept.pop())
    if removed:
        log.warning("%d כתוביות בסוף הקובץ הוסרו כהזיות תמלול (מ-%s והלאה): %s",
                    len(removed), stamp(removed[-1].start),
                    " · ".join(r.text.replace("\n", " ")[:30] for r in reversed(removed)))
    return kept


def merge_short(cues: list["Cue"]) -> list["Cue"]:
    """מאחד כתוביות קצרות וצמודות ליחידת קריאה אחת.

    נמדד מול קובץ כתוביות מקצועי של שירות סטרימינג על אותו סרט: שם
    עשר כתוביות בלבד מתוך 1635 קצרות משנייה, ושלוש-עשרה אחוזים מהן
    מחזיקות שני דוברים עם מקף. אצלנו חמישה-עשר אחוזים ירדו מתחת
    לשנייה ואף כתובית לא איחדה דוברים.

    הסיבה היא ש-_fix_timing אינו יכול להאריך כתובית שהבאה אחריה
    מתחילה מיד — התקרה חוסמת אותו. הפתרון אינו לדחוס אלא לאחד, וזה
    בדיוק מה שהמקצוענים עושים בחילופי דברים מהירים.
    """
    if len(cues) < 2:
        return cues
    out: list[Cue] = []
    merged = 0
    for cue in cues:
        if not out:
            out.append(cue)
            continue
        last = out[-1]
        gap = cue.start - last.end
        short = (last.end - last.start) < config.SRT_MERGE_UNDER
        letters = len(last.text) + len(cue.text) + 1
        span = cue.end - last.start
        if (0 <= gap <= config.SRT_MERGE_GAP and short
                and letters <= config.SRT_MERGE_MAX_CHARS
                and span <= config.SRT_MERGE_MAX_SPAN):
            if _two_speakers(last.text, cue.text):
                # מקף לכל דובר, כמו בקובץ המקצועי
                last.text = f"- {last.text}\n- {cue.text}"
            else:
                last.text = f"{last.text}\n{cue.text}"
            last.end = cue.end
            merged += 1
            continue
        out.append(cue)
    if merged:
        log.info("אוחדו %d כתוביות קצרות ליחידות קריאה", merged)
    return out


def _fix_timing(cues: list[Cue]) -> list[Cue]:
    """מונע חפיפות, אוכף אורך מינימלי/מקסימלי ומנצל שקט כדי להאריך קריאה.

    המעבר הזה נכתב מחדש כי סדר הפעולות הקודם לא היה יציב: כל שלב דרס את
    קודמו. השלב האחרון, שתפקידו היה למנוע חפיפה, היה

        cue.end = max(cue.start + 0.3, nxt.start - 0.04)

    וכשהכתובית הבאה התחילה פחות מ-0.34 שנייה אחרי, הביטוי בחר דווקא את
    cue.start + 0.3 — שהוא גדול מ-nxt.start. כלומר השורה שאמורה הייתה
    למנוע חפיפה היא זו שיצרה אותה. בנוסף היא קבעה אורך של 0.3 שניות,
    הרבה מתחת למינימום, ובכך ביטלה את האכיפה שנעשתה שני שלבים קודם.

    עכשיו יש אילוץ קשיח אחד — לא לגעת בכתובית הבאה — ובתוכו נבחר הסוף
    הרצוי פעם אחת, במעבר יחיד ובלי דריסות.
    """
    gap = config.SRT_GAP
    dropped = 0
    out: list[Cue] = []
    for i, cue in enumerate(cues):
        nxt = cues[i + 1] if i + 1 < len(cues) else None
        # התקרה הקשיחה: לעולם לא נוגעים בכתובית הבאה
        ceiling = (nxt.start - gap) if nxt else float("inf")
        if ceiling <= cue.start:
            # הקלט עצמו חופף. אין מה להציל כאן בלי לדרוס את הבאה
            dropped += 1
            continue

        # מהירות קריאה, בתוך גבולות האורך. נמדד על התווים בלבד — שורה
        # שנשברה לשתיים לא נקראת לאט יותר בגלל תו המעבר
        letters = len(cue.text.replace("\n", " "))
        needed = letters / max(1.0, config.SRT_READ_SPEED)
        want = max(cue.end, cue.start + needed)
        want = min(want, cue.start + config.SRT_MAX_DURATION)
        want = max(want, cue.start + config.SRT_MIN_DURATION)

        cue.end = min(want, ceiling)
        out.append(cue)

    if dropped:
        log.warning("%d כתוביות הושמטו כי הן חפפו לחלוטין את הבאה אחריהן", dropped)
    return [c for c in out if c.end > c.start]


def _hard_wrap(words: list[str], limit: int) -> list[str]:
    """שבירה חמדנית שמבטיחה שאף שורה לא תחרוג מהרוחב.

    רשת הביטחון: קודם, כששום חלוקה מאוזנת לא נמצאה, הקוד החזיר את הטקסט
    כשורה אחת ארוכה — עד 84 תווים, פי שניים מהרוחב המותר. על המסך זה
    נחתך או נדחס.
    """
    lines: list[str] = []
    current = ""
    for word in words:
        while len(word) > limit:          # מילה בודדת ארוכה מהשורה
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:limit])
            word = word[limit:]
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def wrap(text: str) -> str:
    """פיצול לשתי שורות מאוזנות, עם העדפה לשבירה בפיסוק ולא באמצע ביטוי.

    שבירה שכבר קיימת בטקסט נשמרת. merge_short מפריד שני דוברים לשתי
    שורות עם מקפים, ואיחוד עיוור כאן היה מוחק את ההפרדה ומדביק את שני
    הדוברים לשורה אחת — בדיוק ההפך מהכוונה
    """
    if "\n" in text:
        limit = config.SRT_MAX_CHARS_PER_LINE
        kept = [" ".join(part.split()) for part in text.split("\n")]
        kept = [part for part in kept if part]
        # גם מספר השורות, ולא רק רוחבן. שבירה קיימת נשמרה כל עוד כל
        # שורה בנפרד נכנסה ברוחב — ולכן שלוש שורות קצרות עברו בשקט אל
        # הקובץ הסופי. נמדד על קובץ שנמסר למשתמש: שמונה כתוביות בנות
        # שלוש שורות, רובן באורך 30 תווים בלבד, שנכנסות היטב בשתיים
        if (kept and len(kept) <= config.SRT_MAX_LINES
                and all(len(part) <= limit for part in kept)):
            return "\n".join(kept)
        text = " ".join(kept)
    text = " ".join(text.split())
    limit = config.SRT_MAX_CHARS_PER_LINE
    if len(text) <= limit:
        return text

    words = text.split(" ")
    best, best_score = None, float("inf")
    for cut in range(1, len(words)):
        first = " ".join(words[:cut])
        second = " ".join(words[cut:])
        # שתי השורות חייבות להיכנס ברוחב. קודם נבדק כאן
        # limit * SRT_MAX_LINES, כלומר שורה שנייה של עד 84 תווים הוכשרה
        if len(first) > limit or len(second) > limit:
            continue
        score = abs(len(first) - len(second))
        if first.rstrip().endswith((",", ".", "!", "?", ":", "—", "–", ";")):
            score -= 25
        if words[cut - 1] in _OPENERS:
            score += 18
        if second.startswith(("ו", "ש")) and len(words[cut]) <= 3:
            score += 6
        if score < best_score:
            best, best_score = (first, second), score

    if best:
        return best[0] + "\n" + best[1]
    # אין חלוקה מאוזנת לשתי שורות: שוברים חמדנית. עדיף שלוש שורות
    # תקינות מאשר שורה אחת שחורגת מהמסך
    return "\n".join(_hard_wrap(words, limit))


def stamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def finalize(cues: list["Cue"], fps: float = 24.0) -> dict:
    """מעבר אחרון לפני הכתיבה לקובץ. מחזיר מה תוקן.

    ‏render כותב את cue.text כמו שהוא, והעטיפה לשתי שורות קורית פעם
    אחת בלבד ב-build_cues. כל מה שרץ אחרי זה — פיצול כתוביות ארוכות,
    סגירת מרווחים, הצמדה לחיתוכים, ריפוד תרגום חסר — משנה טקסט וזמנים
    ואיש לא בדק אותם שוב.

    נמדד על קובץ אמיתי שנמסר למשתמש, 1778 כתוביות: שורה אחת באורך
    שלילי, חמש מתחת למינימום, ארבע-עשרה מעל המקסימום, שמונה בנות שלוש
    שורות ו-31 שורות שחרגו מ-42 תווים. כולן עברו את כל הבדיקות
    שבדרך, כי הבדיקות רצו לפני השלבים ששברו אותן.

    השלב הזה הוא השער האחרון, והוא מניח שכל מה שלפניו עלול להיות שבור
    """
    frame = 1.0 / max(1.0, fps)
    gap = max(config.SRT_GAP, 2 * frame)
    fixed = {"ריקות": 0, "שורות": 0, "קצרות": 0, "ארוכות": 0, "הפוכות": 0}

    # כתובית שאינה נכנסת בשתי שורות מפוצלת, ולא נדחסת לשלוש. ‏wrap
    # לבדו נופל כאן ל-_hard_wrap ומייצר שורה שלישית
    split_overlong(cues, fps)

    kept: list[Cue] = []
    for cue in cues:
        if not any(ch.isalnum() for ch in (cue.text or "")):
            fixed["ריקות"] += 1
            continue
        if cue.end <= cue.start:
            # סוף לפני התחלה. הכתובית אינה ניתנת להצגה, ונותנים לה
            # את המינימום במקום לזרוק את הטקסט
            fixed["הפוכות"] += 1
            cue.end = cue.start + config.SRT_MIN_DURATION
        wrapped = wrap(cue.text)
        if wrapped != cue.text:
            fixed["שורות"] += 1
            cue.text = wrapped
        kept.append(cue)

    for index, cue in enumerate(kept):
        nxt = kept[index + 1] if index + 1 < len(kept) else None
        roof = (nxt.start - gap) if nxt else float("inf")
        span = cue.end - cue.start
        if span > config.SRT_MAX_DURATION:
            cue.end = cue.start + config.SRT_MAX_DURATION
            fixed["ארוכות"] += 1
        elif span < config.SRT_MIN_DURATION:
            # מאריכים עד המינימום, אבל לעולם לא על חשבון הבאה
            want = min(cue.start + config.SRT_MIN_DURATION, roof)
            if want > cue.end:
                cue.end = want
                fixed["קצרות"] += 1
        # רק חפיפה אמיתית נחתכת. חיתוך לשם שמירת מרווח קיצר כתוביות
        # תקינות אל מתחת למינימום — נמדד כקפיצה מחמש קצרות ל-145
        if nxt and cue.end > nxt.start:
            cue.end = max(cue.start + frame, roof)

    cues[:] = kept
    for position, cue in enumerate(cues, start=1):
        cue.index = position
    return {name: count for name, count in fixed.items() if count}


def render(cues: list[Cue]) -> str:
    blocks = [
        f"{cue.index}\n{stamp(cue.start)} --> {stamp(cue.end)}\n{cue.text}"
        for cue in cues
    ]
    return "\n\n".join(blocks) + "\n"


# סדר הניסיונות לפענוח קובץ כתוביות. BOM קודם, אחר כך UTF-8, ורק
# אז הקידודים הישנים של עברית ומערב אירופה
ENCODINGS = ("utf-8-sig", "utf-8", "cp1255", "iso-8859-8", "cp1252", "latin-1")


def read_subtitle(path: "Path") -> str:
    """קורא קובץ כתוביות בכל קידוד סביר.

    קובצי כתוביות בעברית מופצים לרוב ב-cp1255 ולא ב-UTF-8 — כך הגיע
    גם קובץ מקצועי שנבדק כאן. קריאה עיוורת כ-UTF-8 נכשלת עליהם
    בשגיאה שאינה אומרת דבר למשתמש: "codec can't decode byte 0xbb".

    latin-1 אחרון ברשימה בכוונה: הוא לעולם אינו נכשל, ולכן הוא רשת
    ביטחון שמבטיחה שתמיד יוחזר טקסט כלשהו ולא תיזרק שגיאה
    """
    raw = path.read_bytes()
    for name in ENCODINGS:
        try:
            text = raw.decode(name)
        except (UnicodeDecodeError, LookupError):
            continue
        if name not in ("utf-8-sig", "utf-8"):
            log.info("קובץ הכתוביות פוענח כ-%s ולא כ-UTF-8", name)
        return text
    return raw.decode("latin-1", "replace")


def normalize(source: "Path", target: "Path") -> "Path":
    """כותב עותק ב-UTF-8, כדי שכל מי שקורא אחריו לא יצטרך לנחש."""
    target.write_text(read_subtitle(source), encoding="utf-8")
    return target


def parse(text: str) -> list[Cue]:
    """קורא קובץ SRT בחזרה לרשימת כתוביות."""
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timing = next((line for line in lines if "-->" in line), "")
        if not timing:
            continue
        try:
            left, right = timing.split("-->")
            start, end = _seconds(left), _seconds(right)
        except (ValueError, IndexError):
            continue
        body = "\n".join(lines[lines.index(timing) + 1:]).strip()
        if body:
            cues.append(Cue(len(cues) + 1, start, end, body))
    return cues


def _seconds(stamp: str) -> float:
    stamp = stamp.strip().replace(".", ",")
    hours, minutes, rest = stamp.split(":")
    secs, _, millis = rest.partition(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(secs) + int(millis or 0) / 1000


def slice_file(source: Path, start: float, end: float, dst: Path) -> Path:
    """עותק של הכתוביות לקטע אחד, מוזז כך שהקטע מתחיל בזמן אפס."""
    kept: list[Cue] = []
    for cue in parse(read_subtitle(source)):
        if cue.end <= start or cue.start >= end:
            continue
        kept.append(Cue(
            index=len(kept) + 1,
            start=max(0.0, cue.start - start),
            end=min(end, cue.end) - start,
            text=cue.text,
        ))
    # קטע בלי שום כתובית הוא מצב רגיל לגמרי — שתי דקות של שקט, מוזיקה או
    # קרדיטים. אבל מסנן הכתוביות של ffmpeg מסרב לפתוח קובץ בגודל אפס
    # ("Unable to open"), והקטע היה מפיל את כל הצריבה המקבילית חזרה
    # לתהליך יחיד. כתובית ריקה בת אלפית שנייה פותרת את זה ולא נראית
    if not kept:
        kept = [Cue(index=1, start=0.0, end=0.001, text=" ")]
    dst.write_text(render(kept), encoding="utf-8")
    return dst


def _fits(text: str) -> bool:
    """האם הטקסט נכנס בשתי שורות ברוחב המותר."""
    return wrap(text).count("\n") < config.SRT_MAX_LINES


def _pieces(words: list[str]) -> list[str]:
    """חותך לקטעים, כשכל אחד הוא הארוך ביותר שנכנס בשתי שורות.

    חמדני ובכוונה: קטע ראשון מלא ככל האפשר משאיר פחות קטעים, וכל קטע
    נוסף הוא עוד הבהוב על המסך. השבירה מועדפת על פיסוק — שם הדובר
    עוצר ממילא, ולכן החיתוך אינו מורגש
    """
    out: list[str] = []
    rest = list(words)
    while rest:
        cut = len(rest)
        while cut > 1 and not _fits(" ".join(rest[:cut])):
            cut -= 1
        # אם יש פיסוק מעט לפני הסוף, עדיף לשבור שם
        for back in range(cut, max(1, cut - 4), -1):
            if rest[back - 1].rstrip().endswith((",", ".", "!", "?", ":", ";")):
                cut = back
                break
        out.append(" ".join(rest[:cut]))
        rest = rest[cut:]
    return out


def drop_blank(cues: list["Cue"]) -> int:
    """מסיר כתוביות שאין בהן אות או ספרה. מחזיר כמה הוסרו.

    כתובית שכל תוכנה נקודה, מקף או סימן בודד אינה טקסט — היא שארית
    של תמלול שלא זיהה דיבור, או של סימן פיסוק שנותר לבדו אחרי ניקוי.
    על המסך היא נראית כמו נקודה שצצה משום מקום, ודווח בדיוק כך
    """
    keep = [cue for cue in cues
            if any(ch.isalnum() for ch in (cue.text or ""))]
    removed = len(cues) - len(keep)
    if removed:
        cues[:] = keep
        for position, cue in enumerate(cues, start=1):
            cue.index = position
    return removed


def split_overlong(cues: list["Cue"], fps: float = 24.0) -> int:
    """מפצל כתובית שאינה נכנסת בשתי שורות לכתוביות עוקבות.

    מחזיר כמה כתוביות פוצלו.

    שתי שורות הן תקרה בכל תקן מקצועי — נטפליקס ו-EBU כאחד — והנימוק
    הוא תפיסתי: שורה שלישית מכריחה את העין לשלוש תנועות סריקה בזמן
    שהפריים ממשיך לזוז, והצופה מפספס את התמונה או את הטקסט.

    עד כה הקוד העדיף שלוש שורות על פני שורה שחורגת מהמסך, וזו הייתה
    בחירה בין שתי רעות. הפתרון הנכון הוא השלישי: אותו טקסט, בכמה
    כתוביות עוקבות, כשהזמן מתחלק לפי אורך הטקסט — כי זו בדיוק
    המשמעות של מהירות קריאה.

    שמרני: פיצול שיקצר חלק כלשהו מתחת למינימום לא נעשה כלל, והכתובית
    נשארת כמו שהיתה. עדיף שלוש שורות מאשר כתוביות שמהבהבות
    """
    frame = 1.0 / max(1.0, fps)
    least = 2 * frame
    changed = 0
    out: list[Cue] = []

    for cue in cues:
        if _fits(cue.text):
            out.append(cue)
            continue

        words = " ".join(cue.text.split()).split(" ")
        parts = _pieces(words)
        span = cue.end - cue.start
        usable = span - least * (len(parts) - 1)
        if len(parts) < 2 or usable < config.SRT_MIN_DURATION * len(parts):
            # אין מספיק זמן לפצל בלי להבהב. נשאר כמו שהוא, וזה מודע
            out.append(cue)
            continue

        letters = sum(len(part) for part in parts) or 1
        at = cue.start
        for number, part in enumerate(parts):
            share = max(config.SRT_MIN_DURATION, usable * len(part) / letters)
            end = cue.end if number == len(parts) - 1 else at + share
            out.append(Cue(index=cue.index, start=at, end=end, text=part))
            at = end + least
        changed += 1

    if changed:
        cues[:] = out
        for position, cue in enumerate(cues, start=1):
            cue.index = position
    return changed


def close_gaps(cues: list["Cue"], fps: float = 24.0) -> int:
    """סוגר מרווחים קטנים בין כתוביות. מחזיר כמה שונו.

    זה חוק התזמון של נטפליקס (Subtitle Timing Guidelines, סעיף 5):
    מרווח בין כתוביות הוא או שני פריימים, או חצי שנייה ומעלה — ואין
    אמצע. מרווח של שלושה עד אחד-עשר פריימים חייב להיסגר לשניים.

    הנימוק אינו אסתטי. מרווח של שליש שנייה בין שתי כתוביות הוא הבהוב:
    העין קולטת היעלמות, חוזרת אל התמונה, ומיד נמשכת בחזרה לטקסט חדש.
    המחיר הוא קריאה כפולה של אותו מידע. או שהטקסט ממשיך רצוף, או
    שנותנים לעין זמן אמיתי לחזור לתמונה

    שמרני: רק הסוף של הכתובית הקודמת מוארך, ורק אם זה אינו חורג
    מהאורך המרבי. ההתחלה של הכתובית הבאה אינה זזה, כי היא מתוזמנת
    לפריים הראשון של האודיו וזה האילוץ החזק יותר
    """
    if len(cues) < 2:
        return 0
    frame = 1.0 / max(1.0, fps)
    least = 2 * frame
    changed = 0
    for cue, nxt in zip(cues, cues[1:]):
        gap = nxt.start - cue.end
        # חצי פריים סבילות, כי המרווח מגיע מחשבון בנקודה צפה: מרווח
        # של שני פריימים בדיוק יצא גדול מהיעד בספרה ה-15, והקוד "סגר"
        # אותו למה שהוא כבר היה
        if gap <= least + 0.5 * frame or gap >= 0.5:
            continue
        want = nxt.start - least
        if want - cue.start > config.SRT_MAX_DURATION:
            # הארכה שתעבור את האורך המרבי אינה שיפור. כאן המרווח
            # נשאר כמו שהוא, וזו החלטה מודעת ולא השמטה
            continue
        cue.end = want
        changed += 1
    return changed


def snap_to_cuts(cues: list["Cue"], cuts: list[float],
                 fps: float = 24.0) -> int:
    """מרחיק כתוביות מחיתוכי צילום. מחזיר כמה שונו.

    נטפליקס אוסרת על כתובית לחצות חיתוך, ואם אין ברירה — לשמור 12
    פריימים ממנו. הנימוק: כתובית שמופיעה רגע לפני חיתוך נקראת פעמיים,
    כי החיתוך מחזיר את העין אל הטקסט.

    שמרני בכוונה: רק קצה שקרוב לחיתוך מוזז, ורק אם ההזזה אינה מקצרת
    את הכתובית מתחת למינימום ואינה דורכת על השכנה. חיתוך שנופל באמצע
    כתובית ארוכה נשאר כמו שהוא — פיצולה היה שובר את הטקסט, וזו החלטת
    עריכה ולא חשבון
    """
    if not cues or not cuts:
        return 0
    guard = 12.0 / max(1.0, fps)
    changed = 0

    for index, cue in enumerate(cues):
        floor = cues[index - 1].end + config.SRT_GAP if index else 0.0
        roof = (cues[index + 1].start - config.SRT_GAP
                if index + 1 < len(cues) else cue.end + guard)

        inside = [c for c in cuts if cue.start < c < cue.end]
        if not inside:
            # קצה שיושב ממש לפני חיתוך — מושכים אותו אל החיתוך עצמו
            near = [c for c in cuts if 0 < c - cue.end <= guard]
            if near and near[0] <= roof:
                cue.end = near[0]
                changed += 1
            continue

        first, last = inside[0], inside[-1]
        if first - cue.start <= guard:
            # החיתוך ממש בהתחלה: הכתובית מתחילה עליו ולא לפניו
            if first >= floor and cue.end - first >= config.SRT_MIN_DURATION:
                cue.start = first
                changed += 1
                continue
        if cue.end - last <= guard:
            # החיתוך ממש בסוף: הכתובית נגמרת עליו
            if last - cue.start >= config.SRT_MIN_DURATION:
                cue.end = last
                changed += 1
    return changed
