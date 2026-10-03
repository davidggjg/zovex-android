"""רשימת מורשים שנשמרת לקובץ — נוספים ונמחקים מתוך טלגרם, בלי לגעת ב-.env."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

PATH = Path(config.ALLOWLIST_FILE)


def _load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"users": {}}
    if not isinstance(data, dict) or not isinstance(data.get("users"), dict):
        return {"users": {}}
    return data


def _save(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PATH)


def is_allowed(user_id: int) -> bool:
    return str(user_id) in _load()["users"]


def add(user_id: int, label: str = "") -> bool:
    """מחזיר True אם זו הוספה חדשה."""
    data = _load()
    key = str(user_id)
    new = key not in data["users"]
    data["users"][key] = label or data["users"].get(key, "")
    _save(data)
    log.info("מורשה: %s (%s)", key, label)
    return new


def remove(user_id: int) -> bool:
    data = _load()
    if data["users"].pop(str(user_id), None) is None:
        return False
    _save(data)
    log.info("הוסר: %s", user_id)
    return True


def listing() -> list[tuple[int, str]]:
    out = []
    for key, label in _load()["users"].items():
        try:
            out.append((int(key), label))
        except ValueError:
            continue
    return sorted(out)
