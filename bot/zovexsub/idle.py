"""למידה בזמן מת: כשאף אחד לא משתמש בבוט, הוא חוקר את ספריית האולפן.

הספרייה מחזיקה כתוביות אולפן **בעברית בלבד**. מהן אפשר ללמוד סגנון,
אבל לא איך משפט מסוים בשפת המקור הופך לעברית של אולפן — כי אין צד
מקור. הפתרון המוכר לזה הוא back-translation: מתרגמים את העברית
האנושית **אחורה** לאנגלית, ומקבלים זוג שבו העברית אמיתית והמקור
סינתטי. Zhang, Haddow & Birch (ICML 2023) מדדו שזוגות כאלה בפרומפט
מתקרבים לזוגות אמיתיים, ועמידים יותר מדוגמאות מכל סוג אחר — כי מה
שהמודל מחקה הוא הצד העברי, וזה בדיוק הצד שאדם כתב.

כך כל קובץ אולפן ששלחת הופך, לאט ובזמן שאיש לא עובד, לזיכרון תרגום:
"כשאומרים את זה באנגלית, האולפן כתב ככה". בזמן תרגום זה רק חיפוש
בקובץ — הלמידה כבר נעשתה.

שלושה בלמים, כי מכסה שנגמרה כבר הפילה סרט באמצע:
- רץ רק כשאין שום עבודה, ורק אחרי IDLE_QUIET דקות של שקט
- תקרה יומית של קטעים (IDLE_DAILY)
- כל שגיאה מהמודל — מכסה או כל דבר אחר — עוצרת ללמידה לזמן ארוך

מגבלה: המקור הסינתטי הוא אנגלית, ולכן זה עוזר לסרטים באנגלית. סרט
טורקי לא יתאים לזוגות האלה בחיפוש.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path

from . import config, gemini, memory, studio

log = logging.getLogger(__name__)

BACK_SYSTEM = """אתה מקבל קטע רצוף מכתוביות עבריות של אולפן, מסרט או מסדרה
שצולמו במקור באנגלית. לכל שורה כתוב את השורה באנגלית שממנה היא כנראה
תורגמה — אנגלית מדוברת וטבעית של סרט, ולא תרגום מילולי של העברית.

השתמש בהקשר של השורות שלפני ואחרי כדי להבין מי מדבר ועל מה. שמות
נשארים כמו שהם, באותיות לטיניות. אם שורה היא שם בלבד או קריאה בלי
תוכן, החזר אותה כמו שהיא.

מחזיר תמיד JSON בלבד."""

_state = {"busy_at": 0.0, "pause_until": 0.0, "day": "", "done_today": 0}


def ledger_path() -> Path:
    return Path(config.MEMORY_PATH).parent / "library" / "backtranslated.json"


def _key(block: dict) -> str:
    return hashlib.sha1("\n".join(block.get("lines", [])).encode(
        "utf-8")).hexdigest()[:16]


def _ledger() -> set[str]:
    try:
        return set(json.loads(ledger_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _save_ledger(done: set[str]) -> None:
    try:
        ledger_path().parent.mkdir(parents=True, exist_ok=True)
        ledger_path().write_text(json.dumps(sorted(done)), encoding="utf-8")
    except OSError as exc:
        log.warning("רישום הלמידה לא נשמר (%s)", exc)


def pending() -> list[dict]:
    """קטעי סגנון שעוד לא נלמדו."""
    done = _ledger()
    return [b for b in studio.load_style() if _key(b) not in done]


def quiet(busy: bool, now: float | None = None) -> bool:
    """האם מותר ללמוד עכשיו. נקרא בכל סבב, ומעדכן מתי היה עומס."""
    now = time.monotonic() if now is None else now
    if busy:
        _state["busy_at"] = now
        return False
    if now < _state["pause_until"]:
        return False
    if gemini.waiting_for_key():
        return False
    return now - _state["busy_at"] >= config.IDLE_QUIET * 60


def _budget() -> bool:
    today = time.strftime("%Y-%m-%d")
    if _state["day"] != today:
        _state["day"], _state["done_today"] = today, 0
    return _state["done_today"] < config.IDLE_DAILY


async def learn_one(block: dict) -> int:
    """מתרגם קטע אחד אחורה ושומר את הזוגות. מחזיר כמה נוספו."""
    rows = [line for line in block.get("lines", []) if line.strip()]
    if not rows:
        return 0
    listing = "\n".join(f"[{i}] {line}" for i, line in enumerate(rows))
    schema = {"type": "object", "properties": {"lines": {
        "type": "array", "items": {"type": "object", "properties": {
            "i": {"type": "integer"}, "en": {"type": "string"}},
            "required": ["i", "en"]}}}, "required": ["lines"]}
    result = await asyncio.wait_for(gemini.ask_json(
        BACK_SYSTEM,
        f"{listing}\n\nהחזר JSON: {{\"lines\": [{{\"i\": <אינדקס>, "
        f"\"en\": \"<English>\"}}]}}",
        schema=schema, temperature=0.2), timeout=180)
    items = result.get("lines") if isinstance(result, dict) else None
    pairs = []
    for item in items or []:
        try:
            index, english = int(item["i"]), str(item["en"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        # תשובה שאינה אנגלית אינה מקור — היא תיכנס לחיפוש ותזהם אותו
        if 0 <= index < len(rows) and english and english.isascii():
            pairs.append((english, rows[index]))
    return memory.add(pairs, source=f"חזרה:{block.get('from', '')}")


async def tick(busy: bool) -> int:
    """סבב אחד: לומד קטע אחד אם מותר. מחזיר כמה זוגות נוספו."""
    if not config.IDLE_LEARN or not quiet(busy) or not _budget():
        return 0
    todo = pending()
    if not todo:
        return 0
    block = todo[0]
    try:
        added = await learn_one(block)
    except (asyncio.TimeoutError, gemini.GeminiError) as exc:
        # כל תקלה מהמודל היא סימן לעצור. מכסה שנשרפת כאן חסרה אחר כך
        # לסרט אמיתי
        _state["pause_until"] = time.monotonic() + config.IDLE_BACKOFF * 60
        log.warning("למידה בזמן מת נעצרה ל-%d דקות (%s)",
                    config.IDLE_BACKOFF, exc)
        return 0
    done = _ledger()
    done.add(_key(block))
    _save_ledger(done)
    _state["done_today"] += 1
    log.info("למידה בזמן מת: %d זוגות מקטע של %s · נשארו %d קטעים",
             added, block.get("from", "?"), len(todo) - 1)
    return added


async def run_forever(is_busy) -> None:
    """הלולאה שרצה ברקע לאורך חיי הבוט. ‏is_busy() אומר אם עבודה רצה."""
    log.info("למידה בזמן מת פעילה: אחרי %d דקות שקט, עד %d קטעים ביום",
             config.IDLE_QUIET, config.IDLE_DAILY)
    while True:
        try:
            await asyncio.sleep(config.IDLE_EVERY)
            await tick(bool(is_busy()))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — הלמידה לא מפילה את הבוט
            log.warning("סבב למידה נכשל: %s", exc)
            _state["pause_until"] = time.monotonic() + config.IDLE_BACKOFF * 60
