"""קליינט ל-Gemini: מצב JSON לתרגום, ומצב מחובר-לחיפוש למעבר החקר."""
from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx

from . import config
from .keypool import KeyPool

log = logging.getLogger(__name__)

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_pool = KeyPool("gemini", config.GEMINI_API_KEYS)

# שמות מודלים אצל גוגל מתחלפים (2.5-pro הוסר, 3.1 נכנס). במקום לרדוף אחריהם
# בקוד, אנחנו שואלים את ה-API מה זמין ובוחרים את הטוב ביותר, פעם אחת.
_resolved: dict[str, str] = {}
_resolve_lock = asyncio.Lock()


class GeminiError(RuntimeError):
    pass


async def _list_models(key: str) -> list[str]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE}", params={"key": key, "pageSize": 200},
                                timeout=60.0)
    resp.raise_for_status()
    names = []
    for item in resp.json().get("models", []):
        if "generateContent" not in (item.get("supportedGenerationMethods") or []):
            continue
        names.append(str(item.get("name", "")).removeprefix("models/"))
    return names


def _score(name: str, family: str) -> tuple:
    """ככל שהציון גבוה יותר, המודל מועדף."""
    version = re.search(r"(\d+)\.(\d+)", name)
    major, minor = (int(version.group(1)), int(version.group(2))) if version else (0, 0)
    return (
        family in name,                     # pro / flash לפי מה שביקשנו
        "latest" in name,                   # כינוי יציב עדיף על גרסה מוקפאת
        major, minor,
        "preview" not in name and "exp" not in name,
    )


_BAD = ("embedding", "vision", "tts", "image", "audio", "live", "aqa", "learnlm")


async def _resolve(model: str) -> str:
    """מחזיר את שם המודל שבאמת קיים — זה שביקשנו, או החלופה הטובה ביותר."""
    if model in _resolved:
        return _resolved[model]
    async with _resolve_lock:
        if model in _resolved:
            return _resolved[model]
        family = "flash" if "flash" in model else "pro"
        key = await _pool.wait_for_free()
        try:
            names = [n for n in await _list_models(key)
                     if not any(bad in n for bad in _BAD)]
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("לא הצלחתי לקרוא את רשימת המודלים: %s", exc)
            return model
        if model in names:
            _resolved[model] = model
            return model
        candidates = [n for n in names if family in n] or names
        if not candidates:
            return model
        best = max(candidates, key=lambda n: _score(n, family))
        log.warning("המודל %s לא זמין — עובר ל-%s", model, best)
        _resolved[model] = best
        return best


# מודלים שהמפתח חסום מהם לגמרי (למשל pro בתוכנית החינמית, limit: 0)
_dead: set[str] = set()


def _chain(model: str) -> list[str]:
    """שרשרת ירידה: המודל שביקשנו, ואחריו החלופות החלשות יותר."""
    options = [model, config.GEMINI_FALLBACK_MODEL, config.GEMINI_LAST_RESORT_MODEL]
    seen, chain = set(), []
    for name in options:
        if name and name not in seen:
            seen.add(name)
            chain.append(name)
    return chain


async def _call(model: str, body: dict, *, timeout: float = 300.0) -> dict:
    """שולח את הבקשה, ויורד למודל הבא כשהנוכחי חסום או עמוס."""
    last_error = "לא ידוע"

    async with httpx.AsyncClient() as client:
        for wanted in _chain(model):
            name = await _resolve(wanted)
            if name in _dead:
                continue

            for attempt in range(1, 5):
                key = await _pool.wait_for_free()
                try:
                    resp = await client.post(
                        f"{BASE}/{name}:generateContent",
                        params={"key": key}, json=body,
                        timeout=httpx.Timeout(timeout, connect=30.0),
                    )
                except httpx.HTTPError as exc:
                    last_error = f"רשת: {exc}"
                    await asyncio.sleep(min(2 ** attempt, 15))
                    continue

                if resp.status_code == 200:
                    _pool.report_ok(key)
                    return resp.json()

                text = resp.text[:400]

                if resp.status_code == 429:
                    # "limit: 0" = המודל חסום לתוכנית הזו, לא עומס רגעי
                    if "limit: 0" in text:
                        _dead.add(name)
                        log.warning("המודל %s חסום למפתחות האלה — יורד למודל הבא", name)
                        last_error = f"{name} חסום בתוכנית"
                        break
                    _pool.penalize(key)
                    last_error = f"{name}: מכסה זמנית"
                    continue

                if resp.status_code >= 500:
                    last_error = f"{name}: HTTP {resp.status_code}"
                    await asyncio.sleep(min(2 ** attempt, 15))
                    continue

                if resp.status_code == 404:
                    _resolved.pop(wanted, None)
                    refreshed = await _resolve(wanted)
                    if refreshed != name:
                        name = refreshed
                        continue
                    last_error = f"{name} לא קיים"
                    break

                if resp.status_code in (400, 401, 403) and "API_KEY" in text.upper():
                    _pool.penalize(key, 3600)
                    last_error = "מפתח נדחה"
                    continue

                raise GeminiError(f"Gemini HTTP {resp.status_code}: {text}")

            log.warning("עובר למודל הבא אחרי %s", last_error)

    raise GeminiError(f"כל המודלים נכשלו — {last_error}")


def _text_of(payload: dict) -> str:
    out = []
    for cand in payload.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            if isinstance(part.get("text"), str):
                out.append(part["text"])
    return "".join(out).strip()


async def ask_json(system: str, user: str, *, schema: dict | None = None,
                   model: str | None = None, temperature: float = 0.2) -> object:
    """שאלה שהתשובה שלה חייבת להיות JSON תקין."""
    gen: dict = {"temperature": temperature, "response_mime_type": "application/json",
                 "maxOutputTokens": 65536}
    if schema:
        gen["response_schema"] = schema
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": gen,
    }
    for attempt in range(2):
        payload = await _call(model or config.GEMINI_MODEL, body)
        parsed = _loose_json(_text_of(payload))
        if parsed is not None:
            return parsed
        log.warning("התקבל JSON לא תקין, מנסה שוב (%d)", attempt + 1)
    raise GeminiError("לא התקבל JSON תקין מ-Gemini")


async def research(system: str, user: str) -> str:
    """מעבר חקר מחובר לחיפוש Google — לשמות, מונחים, ציטוטים ומושגים.

    לחיפוש יש מכסה חינמית נפרדת וקטנה. כשהיא נגמרת אנחנו חוזרים על אותה
    שאלה בלי החיפוש: אימות עובדתי של שמות אובד, אבל מיפוי הדוברים
    והמגדרים — החלק שמחזיק את כל דיוק התרגום — עדיין נוצר.
    """
    base = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192},
    }
    grounded = {**base, "tools": [{"google_search": {}}]}

    # המעבר הזה לא קריטי לתרגום, ולכן הוא לא מחזיק את התור יותר מדי זמן
    for body, label in ((grounded, "עם חיפוש"), (base, "בלי חיפוש")):
        try:
            text = _text_of(await asyncio.wait_for(
                _call(config.GEMINI_MODEL, body), timeout=config.RESEARCH_TIMEOUT))
            if text:
                return text
            log.warning("החקר %s חזר ריק", label)
        except asyncio.TimeoutError:
            log.warning("החקר %s עבר את תקרת הזמן (%ds)", label, config.RESEARCH_TIMEOUT)
        except GeminiError as exc:
            log.warning("החקר %s נכשל: %s", label, exc)

    log.warning("ממשיכים בלי מסמך הנחיות")
    return ""


def _loose_json(raw: str):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = raw.find(opener), raw.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(raw[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None
