"""הגדרות שנשמרות לכל צ'אט, כדי לא לשאול את אותן שאלות בכל פרק.

המשתמש מעלה פרקים של אותה סדרה שוב ושוב ועונה בכל פעם על אותן חמש
שאלות באותן תשובות. זיכרון הופך את זה ללחיצה אחת, ומשאיר את השינוי
זמין למי שבאמת רוצה לשנות משהו.

אותו דפוס כמו allowlist: קובץ JSON קטן לצד הקוד, בלי מסד נתונים.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

PATH = Path(config.PREFS_FILE)

# מה שנשמר, ומה שמוצג למי שעוד לא בחר דבר
FIELDS = ("size", "font", "look", "cover", "speed")
DEFAULTS = {
    "size": "בינוני",
    "font": "ברירת מחדל",
    "look": "קו",
    "cover": "לא",
    "speed": "איכותי",
}

# תווית קריאה לכל ערך. הטקסט הגולמי שנשמר אינו תמיד ברור בעין
LABELS = {
    "size": {"קטן": "📏 קטן", "בינוני": "📏 בינוני", "גדול": "📏 גדול"},
    "font": {"dejavu": "🔤 DejaVu", "free": "🔤 FreeSans",
             "ברירת מחדל": "🔤 גופן ברירת מחדל"},
    "look": {"קופסה": "⬛ רקע שחור", "לבן": "⬜ לבן בלבד",
             "קו": "✒️ לבן עם קו מתאר"},
    "cover": {"כן": "🖼️ תמונה משלי", "לא": "🎞️ פריים מהסרטון"},
    "speed": {"איכותי": "💎 צריבה איכותית", "מהיר": "⚡ צריבה מהירה"},
}


def _load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except OSError as exc:
        log.warning("שמירת ההגדרות נכשלה: %s", exc)


def get(chat_id) -> dict:
    """ההגדרות של הצ'אט, מושלמות בברירות מחדל."""
    saved = _load().get(str(chat_id)) or {}
    return {name: saved.get(name) or DEFAULTS[name] for name in FIELDS}


def remember(chat_id, values: dict) -> None:
    """שומר רק שדות מוכרים, כדי שקובץ פגום לא ישבור את הזרימה."""
    data = _load()
    keep = {name: values[name] for name in FIELDS if values.get(name)}
    if not keep:
        return
    data[str(chat_id)] = keep
    _save(data)
    log.info("הגדרות נשמרו לצ'אט %s: %s", chat_id, summary(keep))


def label(field: str, value: str) -> str:
    return LABELS.get(field, {}).get(value, value or "—")


def summary(values: dict) -> str:
    """שורה אחת קריאה עם כל מה שנבחר."""
    return " · ".join(label(name, values.get(name, "")) for name in FIELDS)
