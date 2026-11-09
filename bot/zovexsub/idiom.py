"""עברית ישראלית-קולנועית: מה אולפן אומר, ומה אנחנו אומרים במקומו.

הספרייה האולפנית אינה רק תזמונים. היא קורפוס של עברית שנכתבה
לקולנוע בידי אדם — והשוואה שלה אל הפלט שלנו מראה בדיוק איפה אנחנו
נשמעים מתורגמים ולא ישראליים.

הכלי לכך מבוסס ומוכר בבלשנות קורפוס ונקרא **keyness**: שתי רשימות
תדירות, ומדד שמוציא את מה שאופייני לאחת ולא לאחרת. המדד הסטטיסטי
הוא יחס הנראות (log-likelihood, בנוסח Dunning), וגודל האפקט הוא
‏log ratio — זו הפרקטיקה המקובלת, והיא בדיוק מה שהשתמשו בו כדי
להשוות טקסט מתורגם לטקסט שנכתב במקור (Rayson ועוד, Lancaster).

מה שאינו מבוסס, ואני אומרת זאת במפורש: לא מצאתי מחקר שמזין keyness
בחזרה לפרומפט של מודל. המדידה מוכרת, השימוש הזה הוא שלנו — ולכן
הוא בנוי כך שאפשר לראות את הרשימות, למדוד, ולכבות.

שני פלטים:

**לקסיקון** — "אומרים ככה ולא ככה". הביטויים שאופייניים לאולפן מול
אלה שאופייניים לנו. זה הדבר שהוא ביקש: מילים ישראליות-קולנועיות.

**צורות פנייה** — שורות אולפן אמיתיות שבהן פונים לאשה, ושורות שבהן
פונים לגבר. למעבר מגדר הפנייה אין בעיה להחליט *למי* פונים; הבעיה
היא איך צורה כזאת נשמעת כשהיא נכתבת בידי מקצוען, וכאן הוא רואה את
זה בעיניו
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path

from . import config, studio

log = logging.getLogger(__name__)

# מילה עברית. בלי לטינית ובלי ספרות: מספרים וכתוביות שלא תורגמו
# אינם סגנון
_WORD = re.compile(r"[א-ת]+")
# מילות פונקציה. הן הנפוצות ביותר בכל טקסט עברי, ולכן הן ישתלטו על
# כל רשימת תדירות ולא תלמדנה דבר על סגנון — אבל **רק** כמילה בודדת:
# בצירוף ("אין מצב", "מה הולך") הן דווקא העיקר
_GLUE = {
    "של", "את", "זה", "לא", "אני", "הוא", "היא", "אתה", "אם", "כי",
    "על", "עם", "לי", "לו", "לה", "יש", "אין", "מה", "מי", "כל",
    "אבל", "גם", "רק", "או", "כן", "הם", "הן", "אנחנו", "הזה",
}
# אורך הצירופים שנמדדים. שלוש מילים הוא הגבול שבו צירוף עוד חוזר
# מספיק פעמים כדי להיות מדיד
NGRAMS = (1, 2, 3)
# כמה פעמים צירוף חייב להופיע כדי להיחשב. מתחת לזה הוא רעש
LEAST_SEEN = 4
# כמה ביטויים נכנסים לכל צד בפרומפט
SHOW = 18


def ours_path() -> Path:
    return Path(config.MEMORY_PATH).parent / "ours.jsonl"


def _cache_path() -> Path:
    return Path(config.MEMORY_PATH).parent / "idiom-cache.json"


def remember_ours(lines: list[str], source: str = "") -> int:
    """שומר את הפלט שלנו, כדי שיהיה מול מה להשוות.

    בלי הצד הזה אין keyness בכלל: רשימת תדירות אחת אינה אומרת דבר.
    הקורפוס הזה אינו "תרגומים טובים" ואינו נכנס לשום פרומפט כדוגמה
    — הוא בדיוק ההפך, החשוד שמולו משווים
    """
    kept = [" ".join(line.split()) for line in lines
            if line and _WORD.search(line)]
    if not kept:
        return 0
    store = ours_path()
    store.parent.mkdir(parents=True, exist_ok=True)
    try:
        with store.open("a", encoding="utf-8") as fh:
            for line in kept:
                fh.write(json.dumps({"he": line, "from": source},
                                    ensure_ascii=False) + "\n")
    except OSError as exc:
        log.warning("שמירת הפלט שלנו להשוואה נכשלה (%s)", exc)
        return 0
    _trim_ours()
    return len(kept)


def _trim_ours() -> None:
    """גוזם את הקורפוס שלנו לתקרה, מהסוף.

    בלי זה הקובץ גדל בלי גבול, וחשוב מכך: אנחנו רוצים להשוות את
    האולפן ל**עברית שלנו עכשיו**, לא לזו של לפני חצי שנה. אם תיקנו
    משהו, הטעות הישנה אינה צריכה להמשיך להופיע ברשימה
    """
    store = ours_path()
    try:
        lines = store.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= config.IDIOM_OURS_MAX:
        return
    try:
        store.write_text("\n".join(lines[-config.IDIOM_OURS_MAX:]) + "\n",
                         encoding="utf-8")
    except OSError:
        pass


def load_ours() -> list[str]:
    store = ours_path()
    if not store.exists():
        return []
    out = []
    for line in store.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("he"):
            out.append(row["he"])
    return out


def studio_lines() -> list[str]:
    """כל שורות האולפן, מבנק הסגנון."""
    out: list[str] = []
    for block in studio.load_style():
        out.extend(block.get("lines", []))
    return out


def _grams(lines: list[str]) -> Counter:
    """ספירת צירופים של מילה, שתיים ושלוש."""
    counts: Counter = Counter()
    for line in lines:
        words = _WORD.findall(line)
        for size in NGRAMS:
            for at in range(len(words) - size + 1):
                gram = tuple(words[at:at + size])
                if size == 1 and gram[0] in _GLUE:
                    continue
                if size == 1 and len(gram[0]) < 3:
                    continue
                counts[" ".join(gram)] += 1
    return counts


def _keyness(mine: int, theirs: int,
             mine_total: int, theirs_total: int) -> tuple[float, float]:
    """יחס הנראות וגודל האפקט לצירוף אחד.

    ‏G² בנוסח Dunning: כמה בלתי סביר שההפרש בתדירות הוא מקרי.
    ו-log ratio: כמה גדול ההפרש בפועל. שניהם נחוצים — צירוף נפוץ
    מאוד יכול לקבל G² עצום על הפרש זניח, וצירוף נדיר יכול להיראות
    כהפרש עצום בלי שום מובהקות
    """
    if not mine_total or not theirs_total:
        return 0.0, 0.0
    expect_mine = mine_total * (mine + theirs) / (mine_total + theirs_total)
    expect_theirs = theirs_total * (mine + theirs) / (mine_total + theirs_total)
    g = 0.0
    if mine and expect_mine:
        g += mine * math.log(mine / expect_mine)
    if theirs and expect_theirs:
        g += theirs * math.log(theirs / expect_theirs)
    g *= 2
    # חלקות: צירוף שאינו מופיע כלל בצד אחד אינו "אינסוף"
    rate_mine = (mine + 0.5) / mine_total
    rate_theirs = (theirs + 0.5) / theirs_total
    return g, math.log2(rate_mine / rate_theirs)


def compare() -> dict:
    """מה אופייני לאולפן, ומה אופייני לנו. ריק כששני הצדדים קטנים."""
    theirs = studio_lines()
    mine = load_ours()
    if len(theirs) < config.IDIOM_MIN_LINES or \
            len(mine) < config.IDIOM_MIN_LINES:
        return {}
    their_grams, my_grams = _grams(theirs), _grams(mine)
    their_total = sum(their_grams.values())
    my_total = sum(my_grams.values())
    if not their_total or not my_total:
        return {}

    studio_side, ours_side = [], []
    for gram in set(their_grams) | set(my_grams):
        here, there = their_grams.get(gram, 0), my_grams.get(gram, 0)
        if here + there < LEAST_SEEN:
            continue
        g, ratio = _keyness(here, there, their_total, my_total)
        # 10.83 הוא הסף של p<0.001 בדרגת חופש אחת — הסף המקובל
        # בניתוח keyness, ולא מספר שבחרתי
        if g < 10.83:
            continue
        # והפרש של פחות מפי שניים אינו שווה את מקומו בפרומפט
        if abs(ratio) < 1.0:
            continue
        row = {"gram": gram, "g": round(g, 1), "ratio": round(ratio, 2),
               "studio": here, "ours": there}
        (studio_side if ratio > 0 else ours_side).append(row)

    studio_side.sort(key=lambda r: -r["g"])
    ours_side.sort(key=lambda r: -r["g"])
    studio_side = _longest_only(studio_side)
    ours_side = _longest_only(ours_side)
    return {
        "studio_lines": len(theirs), "our_lines": len(mine),
        "studio": studio_side[:SHOW * 3],
        "ours": ours_side[:SHOW * 3],
    }


def _longest_only(rows: list[dict]) -> list[dict]:
    """מסיר חיתוכים חופפים של אותו ביטוי.

    נמדד: שמונה-עשר המקומות ברשימה התמלאו בשלושה ביטויים בפועל —
    "מה הולך", "מה הולך כאן", "הולך כאן", "כאן בכלל" וכן הלאה, כולם
    אותו דבר חתוך אחרת. ביטוי קצר שכמעט כל הופעותיו הן בתוך ביטוי
    ארוך יותר אינו מוסיף מידע, והארוך הוא המדויק
    """
    # ‫מהארוך לקצר, ולא לפי המובהקות. נמדד: ברשימה ממוינת לפי G²
    # הקצרים מגיעים ראשונים, נכנסים, ואז הארוך נבדק מול הקצר —
    # כלומר הסינון רץ בכיוון ההפוך ולא סינן דבר
    out: list[dict] = []
    for row in sorted(rows, key=lambda r: (-len(r["gram"].split()), -r["g"])):
        gram = row["gram"]
        inside = next(
            (kept for kept in out
             if len(kept["gram"]) > len(gram)
             and (f" {gram} " in f" {kept['gram']} ")
             # ‫ורק כשהוא כמעט תמיד שם. "רגע" שמופיע גם לבדו הוא
             # ביטוי בזכות עצמו
             and kept["studio"] + kept["ours"]
             >= 0.8 * (row["studio"] + row["ours"])),
            None)
        if inside is None:
            out.append(row)
    # והחזרה לסדר המובהקות, שהוא סדר החשיבות
    out.sort(key=lambda r: -r["g"])
    return out


def _fingerprint() -> str:
    """חתימה זולה של שני הקורפוסים, כדי לדעת אם החישוב עדיין תקף."""
    parts = []
    for store in (studio.style_path(), ours_path()):
        try:
            stat = store.stat()
            parts.append(f"{int(stat.st_size)}")
        except OSError:
            parts.append("0")
    return "-".join(parts)


def cached_compare() -> dict:
    """כמו compare, אבל לא מחשב מחדש בכל חלון תרגום.

    הספירה היא על עשרות אלפי שורות. בחלון בודד זה זניח, אבל חלון
    תרגום נקרא עשרות פעמים לכל סרט, ושם זה כבר דקות של מעבד שאין
    להן שום תמורה — הקורפוסים אינם משתנים באמצע עבודה
    """
    want = _fingerprint()
    store = _cache_path()
    if store.exists():
        try:
            held = json.loads(store.read_text(encoding="utf-8"))
            if held.get("fingerprint") == want:
                return held.get("data") or {}
        except (ValueError, OSError):
            pass
    data = compare()
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps({"fingerprint": want, "data": data},
                                    ensure_ascii=False),
                         encoding="utf-8")
    except OSError as exc:
        log.warning("מטמון הלקסיקון לא נשמר (%s)", exc)
    return data


# ───────── צורות פנייה, מתוך שורות אולפן אמיתיות ─────────
#
# הבעיה בהתאמת מגדר הפנייה אינה ההחלטה למי פונים — זו עבודה של הקשר,
# והיא נעשית. הבעיה היא שצורה נכונה דקדוקית עדיין יכולה להישמע כמו
# ספר לימוד. לכן נכנסות לפרומפט שורות שמקצוען כתב, ובהן בדיוק אותה
# צורה שהמודל עומד להשתמש בה

_TO_WOMAN = re.compile(
    r"(?<!\w)(את|אותך|שלך|לך|איתך|בואי|תני|קחי|שבי|לכי|חכי|תסתכלי|"
    r"תגידי|תשמעי|תראי|דעי|סעי|קומי|רוצה|יכולה|צריכה|הולכת|אומרת|"
    r"מבינה|יודעת)(?!\w)")
_TO_MAN = re.compile(
    r"(?<!\w)(אתה|בוא|תן|קח|שב|לך|חכה|תסתכל|תגיד|תשמע|תראה|דע|סע|"
    r"קום|רוצה|יכול|צריך|הולך|אומר|מבין|יודע)(?!\w)")
# מילים ששתי הצורות שלהן זהות בכתיב, ולכן אינן מעידות על כלום
_AMBIGUOUS = re.compile(r"(?<!\w)(רוצה|לך|שלך|אותך)(?!\w)")


def addressee_examples(which: str, most: int = 0) -> list[str]:
    """שורות אולפן שבהן פונים לאשה ("יחידה") או לגבר ("יחיד")."""
    most = most or config.IDIOM_GENDER_EXAMPLES
    want = _TO_WOMAN if which == "יחידה" else _TO_MAN
    avoid = _TO_MAN if which == "יחידה" else _TO_WOMAN
    out = []
    for line in studio_lines():
        bare = _AMBIGUOUS.sub(" ", line)
        if not want.search(bare) or avoid.search(bare):
            continue
        # שורה בת מילה אחת אינה מלמדת על צורה בהקשר
        if len(_WORD.findall(line)) < 3:
            continue
        out.append(line)
        if len(out) >= most:
            break
    return out


def addressee_prompt() -> str:
    """שתי הרשימות כטקסט לפרומפט של מעבר מגדר הפנייה."""
    if not config.IDIOM_GUIDE:
        return ""
    woman = addressee_examples("יחידה")
    man = addressee_examples("יחיד")
    if not woman and not man:
        return ""
    rows = []
    if woman:
        rows.append("פנייה לאשה, מכתוביות אולפן:\n"
                    + "\n".join(f"· {line}" for line in woman))
    if man:
        rows.append("פנייה לגבר, מכתוביות אולפן:\n"
                    + "\n".join(f"· {line}" for line in man))
    return ("כך נשמעות צורות פנייה כשמקצוען כותב אותן. הדוגמאות אינן "
            "קשורות לסרטון שלפניך — קח מהן את **הצורה והמשלב** בלבד:\n"
            + "\n".join(rows) + "\n")


def report() -> str:
    """מה נמדד, לקריאה בטרמינל או בטלגרם."""
    data = cached_compare()
    if not data:
        return (f"אין עוד מה להשוות — צריך לפחות "
                f"{config.IDIOM_MIN_LINES} שורות בכל צד "
                f"(אולפן: {len(studio_lines())}, שלנו: {len(load_ours())})")
    rows = [f"השוואה: {data['studio_lines']} שורות אולפן מול "
            f"{data['our_lines']} שורות שלנו", ""]
    rows.append("אופייני לאולפן (ואנחנו לא אומרים):")
    for row in data["studio"][:SHOW]:
        rows.append(f"  {row['gram']}  ·  אולפן {row['studio']} / "
                    f"שלנו {row['ours']}  ·  G²={row['g']}")
    rows.append("")
    rows.append("אופייני לנו (והאולפן לא אומר):")
    for row in data["ours"][:SHOW]:
        rows.append(f"  {row['gram']}  ·  שלנו {row['ours']} / "
                    f"אולפן {row['studio']}  ·  G²={row['g']}")
    return "\n".join(rows)


# ───────── עברית תקנית: כתיב וסימנים ─────────
#
# זה מה שהוא ביקש, והוא צדק שחסר: אנגלית ועברית הן שני עולמות.
# באנגלית אין כתיב מלא וחסר, אין גרשיים, אין מקף עברי, ואין שאלה
# אם מספר נכתב בספרה או במילה. מודל שמתרגם מאנגלית מביא איתו את
# ההרגלים של אנגלית, והתוצאה נכונה דקדוקית אבל נראית לא נכון.
#
# כל מה שכאן נמדד מהקבצים שלו, ולא נקבע על ידי. ואם האולפן והפלט
# שלנו מסכימים על משהו — הוא אינו נכנס למדריך כלל, כי אין מה לתקן

# המילה בלי אימות הקריאה. "דיבר" ו"דבר" מקבלות אותו מפתח, וכך גם
# "אוקיי" ו"אוקי" — וזה בדיוק ציר הכתיב המלא והחסר
_FILLERS = str.maketrans("", "", "יו")


def _lexicon(lines: list[str]) -> Counter:
    counts: Counter = Counter()
    for line in lines:
        for word in _WORD.findall(line):
            if len(word) >= 3:
                counts[word] += 1
    return counts


def _same_word(one: str, two: str) -> bool:
    """האם שתי הצורות הן אותה מילה בכתיב מלא ובכתיב חסר.

    כלומר: האם הקצרה מתקבלת מהארוכה במחיקת יו״ד ווי״ו בלבד
    """
    long, short = (one, two) if len(one) >= len(two) else (two, one)
    if long == short or len(long) - len(short) > 3:
        return False
    at = 0
    for letter in long:
        if at < len(short) and letter == short[at]:
            at += 1
        elif letter not in "יו":
            return False
    return at == len(short)


def spelling() -> list[dict]:
    """צורות כתיב שהאולפן מעדיף ואנחנו כותבים אחרת.

    הקיבוץ הוא לפי המילה בלי יו״ד ווי״ו, ולכן כל גרסאות הכתיב של
    אותה מילה נופלות לאותה קבוצה בלי שאכתוב רשימה ידנית. בתוך
    הקבוצה נשאלת שאלה אחת: איזו צורה האולפן בחר, והאם אנחנו בחרנו
    אחרת
    """
    theirs, mine = _lexicon(studio_lines()), _lexicon(load_ours())
    if not theirs or not mine:
        return []
    groups: dict[str, set[str]] = {}
    for word in set(theirs) | set(mine):
        groups.setdefault(word.translate(_FILLERS), set()).add(word)

    out = []
    for key, forms in groups.items():
        if len(forms) < 2 or len(key) < 2:
            continue
        their_best = max(forms, key=lambda w: theirs.get(w, 0))
        my_best = max(forms, key=lambda w: mine.get(w, 0))
        if their_best == my_best:
            continue
        # ‫המפתח מקבץ רחב מדי. נמדד: "אני" ו"אינו" קיבלו אותו מפתח
        # ("אנ") והמדריך יצא עם הכלל "כתוב אני ולא אינו" — שתי מילים
        # שונות לגמרי. השער הוא שצורה אחת תתקבל מהשנייה במחיקת
        # אימות קריאה בלבד, וזה בדיוק ציר הכתיב המלא והחסר
        if not _same_word(their_best, my_best):
            continue
        # שתי הצורות חייבות להיות מבוססות בצד שבחר בהן, אחרת זו
        # טעות הקלדה בודדת ולא העדפת כתיב
        if theirs.get(their_best, 0) < LEAST_SEEN or \
                mine.get(my_best, 0) < LEAST_SEEN:
            continue
        # ושהאולפן באמת מעדיף, ולא מפוצל בעצמו
        if theirs.get(their_best, 0) < 2 * theirs.get(my_best, 0):
            continue
        out.append({"use": their_best, "not": my_best,
                    "studio": theirs.get(their_best, 0),
                    "ours": mine.get(my_best, 0)})
    out.sort(key=lambda row: -(row["studio"] + row["ours"]))
    return out[:SHOW]


# סימנים שעברית מקפידה עליהם ואנגלית אינה מכירה כלל
_MARKS = (
    ("גרשיים", "״", '"'),
    ("גרש", "׳", "'"),
    ("שלוש נקודות", "…", "..."),
    ("מקף", "־", "-"),
)


def _marks(lines: list[str]) -> dict:
    text = "\n".join(lines)
    out = {}
    for name, hebrew, plain in _MARKS:
        out[name] = (text.count(hebrew), text.count(plain))
    # דו-שיח: מקף בתחילת שורה. באנגלית זה לא מוסכם ובעברית כן
    out["דו-שיח"] = (
        sum(1 for line in lines
            for row in line.splitlines() if row.strip()[:1] in "-–—־"),
        len([row for line in lines for row in line.splitlines()
             if row.strip()]),
    )
    # מספרים: ספרה או מילה
    digits = sum(1 for line in lines if re.search(r"\d", line))
    out["ספרות"] = (digits, len(lines))
    return out


def conventions() -> list[str]:
    """כלל אחד לכל סימן שבו האולפן ואנחנו נוהגים אחרת."""
    theirs, mine = studio_lines(), load_ours()
    if not theirs or not mine:
        return []
    here, there = _marks(theirs), _marks(mine)
    rows = []
    for name, _, _ in _MARKS:
        heb_t, plain_t = here[name]
        heb_m, plain_m = there[name]
        if heb_t + plain_t < 20 or heb_m + plain_m < 20:
            continue
        share_t = heb_t / (heb_t + plain_t)
        share_m = heb_m / (heb_m + plain_m)
        if share_t > 0.7 and share_m < 0.4:
            rows.append(f"{name}: האולפן כותב את הסימן העברי "
                        f"({share_t * 100:.0f}% מהמקרים) ואנחנו את "
                        f"הלטיני ({share_m * 100:.0f}%) — כתוב עברי")
        elif share_t < 0.3 and share_m > 0.6:
            rows.append(f"{name}: האולפן כותב את הסימן הלטיני "
                        f"ואנחנו את העברי — כתוב לטיני")

    for name, label in (("דו-שיח", "מקף בתחילת שורה לסימון דובר שני"),
                        ("ספרות", "מספרים בספרות ולא במילים")):
        got_t, all_t = here[name]
        got_m, all_m = there[name]
        if all_t < 50 or all_m < 50:
            continue
        share_t, share_m = got_t / all_t, got_m / all_m
        if share_t > share_m * 2 and share_t > 0.08:
            rows.append(f"{label}: האולפן עושה זאת ב-{share_t * 100:.0f}% "
                        f"מהשורות, אנחנו ב-{share_m * 100:.0f}%")
        elif share_m > share_t * 2 and share_m > 0.08:
            rows.append(f"{label}: אנחנו עושים זאת ב-{share_m * 100:.0f}% "
                        f"מהשורות והאולפן רק ב-{share_t * 100:.0f}% — "
                        f"פחות")
    return rows


# ───────── המדריך: מחושב פעם אחת, נקרא בזמן ריצה ─────────
#
# זו הנקודה שבה נבנה המדריך, ובכוונה **לא** בזמן התרגום. ספירת
# צירופים על עשרות אלפי שורות היא עבודת מעבד אמיתית, וחלון תרגום
# נקרא עשרות פעמים לכל סרט. לכן היא רצה פעם אחת — כשנקלטים קבצים
# חדשים — והתוצאה נשמרת כטקסט מוכן. בזמן תרגום זו קריאת קובץ


def guide_path() -> Path:
    return Path(config.MEMORY_PATH).parent / "style-guide.txt"


def gender_path() -> Path:
    return Path(config.MEMORY_PATH).parent / "style-gender.txt"


def build_guide() -> tuple[int, int]:
    """מחשב את המדריך ושומר אותו. מחזיר (אורך המדריך, אורך הפנייה)."""
    blocks = []
    data = cached_compare()
    if data:
        use = [row["gram"] for row in data.get("studio", [])][:SHOW]
        drop = [row["gram"] for row in data.get("ours", [])][:SHOW]
        if use:
            blocks.append("ביטויים שמתרגמי אולפן מעדיפים, וכדאי להעדיף "
                          "כשהם מתאימים להקשר: " + " · ".join(use))
        if drop:
            blocks.append("ביטויים שאופייניים לתרגום מכונה ולא לעברית "
                          "קולנועית. אם אחד מהם עולה לך, חשוב שוב איך "
                          "היה נאמר בפה: " + " · ".join(drop))
    forms = spelling()
    if forms:
        blocks.append("כתיב: כתוב " + " · ".join(
            f"{row['use']} (ולא {row['not']})" for row in forms))
    rules = conventions()
    if rules:
        blocks.append("סימני פיסוק וכתיב עברי:\n"
                      + "\n".join(f"· {row}" for row in rules))

    guide = ""
    if blocks:
        guide = ("עברית קולנועית תקנית — הכל נמדד מכתוביות אולפן "
                 "מקצועיות מול הפלט שלנו, ולא דעה:\n"
                 + "\n".join(blocks) + "\n")
    gender = addressee_prompt()
    try:
        guide_path().parent.mkdir(parents=True, exist_ok=True)
        guide_path().write_text(guide, encoding="utf-8")
        gender_path().write_text(gender, encoding="utf-8")
    except OSError as exc:
        log.warning("המדריך לא נשמר (%s)", exc)
        return 0, 0
    log.info("מדריך הסגנון נבנה: %d תווים, פנייה %d תווים",
             len(guide), len(gender))
    return len(guide), len(gender)


def _read_guide(store: Path) -> str:
    if not config.IDIOM_GUIDE:
        return ""
    try:
        return store.read_text(encoding="utf-8")
    except OSError:
        return ""


def guide() -> str:
    """המדריך לפרומפט התרגום. קריאת קובץ, בלי שום חישוב."""
    return _read_guide(guide_path())


def gender_guide() -> str:
    """דוגמאות הפנייה לפרומפט התאמת המגדר. גם כאן רק קריאה."""
    return _read_guide(gender_path())
