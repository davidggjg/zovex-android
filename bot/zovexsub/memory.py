"""זיכרון תרגום: תרגומים שהמנהל אישר, ומשמשים כדוגמאות בפרומפט.

זו טכניקה מוכרת ולא המצאה — Translation Memory. הספרות חד-משמעית:
התאמות מתוך זיכרון תרגום בתוך הפרומפט מנצחות דוגמאות אקראיות, ואלה
מנצחות פרומפט בלי דוגמאות כלל (Moslem, EAMT 2023). ההתאמה נעשית לפי
**מילים** ולא לפי embeddings, כי כך נמדד כעדיף (EAMT 2026).

ואזהרה אחת שחוזרת בכל המקורות: דוגמה אחת גרועה מקלקלת את התוצאה.
לכן נכנס לכאן רק מה שהמנהל אישר במפורש, ולא כל תרגום שיצא.

הקובץ הוא JSONL — שורה לכל זוג — כדי שאפשר יהיה להוסיף בלי לקרוא
את הכל, ולערוך או למחוק ידנית בלי כלים.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

# מילים קצרות מדי מכדי להעיד על דמיון. בלעדיהן "את" ו"של" היו
# מתאימים כל שורה לכל שורה
_SHORT = 2
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def path() -> Path:
    return Path(config.MEMORY_PATH)


def _words(text: str) -> set[str]:
    """מילות התוכן של השורה, בלי ניקוד ובלי סימני כיווניות."""
    clean = "".join(c for c in text
                    if unicodedata.category(c) not in ("Cf", "Mn"))
    return {w.lower() for w in _WORD.findall(clean) if len(w) > _SHORT}


def add(pairs: list[tuple[str, str]], source: str = "") -> int:
    """מוסיף זוגות מקור→עברית. מחזיר כמה נוספו בפועל.

    כפילויות נדחות: אותו מקור פעמיים אינו מוסיף מידע, ורק מגדיל את
    הסיכוי שדוגמה אחת תשתלט על הפרומפט
    """
    store = path()
    store.parent.mkdir(parents=True, exist_ok=True)
    seen = {item["src"] for item in load()}
    fresh = []
    for src, heb in pairs:
        src, heb = " ".join(src.split()), " ".join(heb.split())
        if not src or not heb or src in seen:
            continue
        # שורה בלי מילות תוכן אינה יכולה להיות מותאמת לכלום
        if not _words(src):
            continue
        seen.add(src)
        fresh.append({"src": src, "he": heb, "from": source})
    if not fresh:
        return 0
    with store.open("a", encoding="utf-8") as fh:
        for item in fresh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    log.info("זיכרון התרגום: נוספו %d זוגות מ-%s (סה\"כ %d)",
             len(fresh), source or "לא ידוע", len(seen))
    return len(fresh)


def load() -> list[dict]:
    store = path()
    if not store.exists():
        return []
    out = []
    for line in store.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("src") and item.get("he"):
            out.append(item)
    return out


def find(lines: list[str], most: int = 0,
         least: float = 0.0) -> list[dict]:
    """ההתאמות הדומות ביותר לשורות שעומדות להיתרגם.

    הציון הוא שיעור המילים המשותפות מתוך האיחוד — התאמה לפי מילים,
    כפי שנמדד עדיף על התאמה לפי משמעות. ההתאמות מוחזרות מהחזקה
    לחלשה, ורק מעל סף: דוגמה רחוקה גרועה מאין דוגמה
    """
    bank = load()
    if not bank:
        return []
    most = most or config.MEMORY_EXAMPLES
    least = least or config.MEMORY_FLOOR

    want: set[str] = set()
    for line in lines:
        want |= _words(line)
    if not want:
        return []

    scored = []
    for item in bank:
        his = _words(item["src"])
        if not his:
            continue
        shared = len(want & his)
        if not shared:
            continue
        score = shared / len(want | his)
        if score >= least:
            scored.append((score, item))
    scored.sort(key=lambda pair: -pair[0])
    return [dict(item, score=round(score, 3))
            for score, item in scored[:most]]


def as_prompt(hits: list[dict]) -> str:
    """ההתאמות כטקסט שנכנס לפרומפט, או מחרוזת ריקה."""
    if not hits:
        return ""
    rows = "\n".join(f"{h['src']}\n⇠ {h['he']}" for h in hits)
    return ("להלן תרגומים שאושרו בעבר כטובים. חקה את הסגנון, את "
            "המשלב ואת צורות הפנייה שבהם — לא את התוכן:\n"
            f"{rows}\n")


def stats() -> str:
    bank = load()
    if not bank:
        return "זיכרון התרגום ריק"
    sources = {item.get("from", "") for item in bank}
    return (f"{len(bank)} זוגות מ-{len(sources)} קבצים")
