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


class GeminiError(RuntimeError):
    pass


async def _call(model: str, body: dict, *, timeout: float = 300.0) -> dict:
    last_error = "לא ידוע"
    async with httpx.AsyncClient() as client:
        for attempt in range(1, 6):
            key = await _pool.wait_for_free()
            try:
                resp = await client.post(
                    f"{BASE}/{model}:generateContent",
                    params={"key": key},
                    json=body,
                    timeout=httpx.Timeout(timeout, connect=30.0),
                )
            except httpx.HTTPError as exc:
                last_error = f"רשת: {exc}"
                await asyncio.sleep(min(2 ** attempt, 20))
                continue

            if resp.status_code == 200:
                _pool.report_ok(key)
                return resp.json()
            if resp.status_code in (429,) or resp.status_code >= 500:
                _pool.penalize(key)
                last_error = f"HTTP {resp.status_code}"
                await asyncio.sleep(min(2 ** attempt, 20))
                continue
            if resp.status_code in (400, 401, 403) and "API_KEY" in resp.text.upper():
                _pool.penalize(key, 3600)
                last_error = "מפתח נדחה"
                continue
            raise GeminiError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")
    raise GeminiError(f"Gemini נכשל — {last_error}")


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
    for candidate_model in [model or config.GEMINI_MODEL, config.GEMINI_FALLBACK_MODEL]:
        payload = await _call(candidate_model, body)
        raw = _text_of(payload)
        parsed = _loose_json(raw)
        if parsed is not None:
            return parsed
        log.warning("%s החזיר JSON לא תקין, מנסה מודל חלופי", candidate_model)
    raise GeminiError("לא התקבל JSON תקין מ-Gemini")


async def research(system: str, user: str) -> str:
    """מעבר חקר מחובר לחיפוש Google — לשמות, מונחים, ציטוטים ומושגים.

    חיפוש ו-JSON מובנה לא יכולים לעבוד יחד באותה קריאה, לכן כאן התשובה טקסט.
    """
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192},
    }
    try:
        payload = await _call(config.GEMINI_MODEL, body)
        return _text_of(payload)
    except GeminiError as exc:
        log.warning("מעבר החקר נכשל, ממשיכים בלעדיו: %s", exc)
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
